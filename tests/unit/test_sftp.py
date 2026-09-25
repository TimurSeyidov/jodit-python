"""SFTP adapter against an in-process paramiko server."""

import errno
import os
import uuid
from io import StringIO
from typing import TYPE_CHECKING

import paramiko
import pytest
from pydantic import ValidationError

from jcpy.config.models import SftpOptions
from jcpy.storage.local import UnsupportedEntryError
from jcpy.storage.pool import Failure
from jcpy.storage.sftp import (
    HostKeyError,
    SftpConnection,
    SftpStorageAdapter,
    classify,
    load_private_key,
    parse_host_key,
)
from tests.adapter_contract import AdapterContract
from tests.sftp_server import PASSWORD, USER, SftpServer, serving

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(scope="module")
def sftp_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("sftp")


@pytest.fixture(scope="module")
def server(sftp_root: Path) -> Iterator[SftpServer]:
    with serving(sftp_root) as running:
        yield running


@pytest.fixture(scope="module")
def plain_server(sftp_root: Path) -> Iterator[SftpServer]:
    with serving(sftp_root, posix_rename=False) as running:
        yield running


def options(server: SftpServer, **values: object) -> SftpOptions:
    return SftpOptions.model_validate(
        {
            "host": "127.0.0.1",
            "port": server.port,
            "username": USER,
            "password": PASSWORD,
            "hostKey": server.public_key,
            **values,
        }
    )


def make_adapter(
    server: SftpServer, root: Path, **values: object
) -> SftpStorageAdapter:
    directory = uuid.uuid4().hex
    (root / directory).mkdir()
    return SftpStorageAdapter(
        options(server, directory=f"/{directory}", **values)
    )


class TestPosixRenameServer(AdapterContract):
    @pytest.fixture
    def adapter(
        self, server: SftpServer, sftp_root: Path
    ) -> Iterator[SftpStorageAdapter]:
        adapter = make_adapter(server, sftp_root)
        yield adapter
        adapter.close()


class TestPlainRenameServer(AdapterContract):
    @pytest.fixture
    def adapter(
        self, plain_server: SftpServer, sftp_root: Path
    ) -> Iterator[SftpStorageAdapter]:
        adapter = make_adapter(plain_server, sftp_root)
        yield adapter
        adapter.close()


class TestHostKeys:
    async def test_unknown_host_key_is_rejected(
        self, server: SftpServer, sftp_root: Path, tmp_path: Path
    ) -> None:
        known_hosts = tmp_path / "known_hosts"
        known_hosts.write_text("")
        adapter = SftpStorageAdapter(
            options(server, hostKey=None, knownHostsFile=str(known_hosts))
        )

        with pytest.raises(paramiko.SSHException, match="not found in known"):
            await adapter.stat("")

    async def test_other_host_key_is_rejected(
        self, server: SftpServer
    ) -> None:
        other = paramiko.ECDSAKey.generate()
        adapter = SftpStorageAdapter(
            options(server, hostKey=f"{other.get_name()} {other.get_base64()}")
        )

        with pytest.raises(paramiko.SSHException):
            await adapter.stat("")

    async def test_known_hosts_file(
        self, server: SftpServer, tmp_path: Path
    ) -> None:
        known_hosts = tmp_path / "known_hosts"
        known_hosts.write_text(
            f"[127.0.0.1]:{server.port} {server.public_key}\n"
        )
        adapter = SftpStorageAdapter(
            options(server, hostKey=None, knownHostsFile=str(known_hosts))
        )

        assert (await adapter.stat("")).is_directory
        adapter.close()

    async def test_system_known_hosts_are_the_default(
        self, server: SftpServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loaded: list[bool] = []
        monkeypatch.setattr(
            paramiko.SSHClient,
            "load_system_host_keys",
            lambda self, filename=None: loaded.append(True),
        )
        adapter = SftpStorageAdapter(options(server, hostKey=None))

        with pytest.raises(paramiko.SSHException):
            await adapter.stat("")
        assert loaded == [True]

    async def test_several_host_keys(self, server: SftpServer) -> None:
        other = paramiko.ECDSAKey.generate()
        adapter = SftpStorageAdapter(
            options(
                server,
                hostKey=[
                    f"{other.get_name()} {other.get_base64()}",
                    f"127.0.0.1 {server.public_key} comment",
                ],
            )
        )

        assert (await adapter.stat("")).is_directory
        adapter.close()

    def test_standard_port_key_name(self) -> None:
        key = paramiko.ECDSAKey.generate()
        adapter = SftpStorageAdapter(
            SftpOptions.model_validate(
                {
                    "host": "example.com",
                    "username": USER,
                    "hostKey": f"{key.get_name()} {key.get_base64()}",
                }
            )
        )
        client = paramiko.SSHClient()

        assert adapter._host_keys == [key]
        assert client.get_host_keys().lookup("example.com") is None

    @pytest.mark.parametrize(
        "value", ["", "garbage", "ssh-ed25519", "ssh-ed25519 not-base64!"]
    )
    def test_invalid_host_key(self, value: str) -> None:
        with pytest.raises(HostKeyError):
            parse_host_key(value)


class TestAuthentication:
    async def test_wrong_password(self, server: SftpServer) -> None:
        adapter = SftpStorageAdapter(options(server, password="wrong"))

        with pytest.raises(paramiko.AuthenticationException):
            await adapter.stat("")

    async def test_private_key(self, sftp_root: Path, tmp_path: Path) -> None:
        key = paramiko.ECDSAKey.generate()
        text = StringIO()
        key.write_private_key(text, password="phrase")
        key_file = tmp_path / "id_ecdsa"
        key.write_private_key_file(str(key_file))

        with serving(sftp_root, client_key=key) as keyed:
            by_text = SftpStorageAdapter(
                options(
                    keyed,
                    password=None,
                    privateKey=text.getvalue(),
                    passphrase="phrase",
                )
            )
            by_file = SftpStorageAdapter(
                options(keyed, password=None, privateKeyFile=str(key_file))
            )

            assert (await by_text.stat("")).is_directory
            assert (await by_file.stat("")).is_directory
            by_text.close()
            by_file.close()

    def test_one_key_source(self) -> None:
        with pytest.raises(ValidationError, match="not both"):
            SftpOptions.model_validate(
                {
                    "host": "h",
                    "username": "u",
                    "privateKey": "x",
                    "privateKeyFile": "y",
                }
            )

    def test_unsupported_private_key(self) -> None:
        with pytest.raises(paramiko.SSHException):
            load_private_key("not a key", None)


class TestConnections:
    async def test_dropped_connection_is_replaced(
        self, sftp_root: Path
    ) -> None:
        with serving(sftp_root) as own:
            adapter = make_adapter(own, sftp_root, connections=1)
            await adapter.write("a.txt", b"a")
            own.drop_connections()

            assert await adapter.read("a.txt") == b"a"
            assert own.accepted == 2
            adapter.close()

    async def test_dropped_connection_is_replaced_before_streaming(
        self, sftp_root: Path
    ) -> None:
        with serving(sftp_root) as own:
            adapter = make_adapter(own, sftp_root, connections=1)
            await adapter.write("a.txt", b"a")
            own.drop_connections()

            assert [c async for c in adapter.iter_file("a.txt")] == [b"a"]
            adapter.close()

    async def test_large_files_are_not_prefetched(
        self,
        server: SftpServer,
        sftp_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("jcpy.storage.sftp.PREFETCH_LIMIT", 10)
        adapter = make_adapter(server, sftp_root)
        await adapter.write("a.bin", b"x" * 100)

        assert b"".join([c async for c in adapter.iter_file("a.bin")]) == (
            b"x" * 100
        )
        adapter.close()

    async def test_login_directory_is_the_default_root(
        self, server: SftpServer, sftp_root: Path
    ) -> None:
        adapter = SftpStorageAdapter(options(server))
        name = f"{uuid.uuid4().hex}.txt"

        await adapter.write(name, b"x")

        assert (sftp_root / name).read_bytes() == b"x"
        adapter.close()

    async def test_failed_replace_keeps_the_target(
        self, plain_server: SftpServer, sftp_root: Path
    ) -> None:
        adapter = make_adapter(plain_server, sftp_root)
        await adapter.write("a.txt", b"keep")
        await adapter.create_directory("dir")

        with pytest.raises(OSError, match=r"."):
            await adapter.move_file("dir", "a.txt")

        assert await adapter.read("a.txt") == b"keep"
        adapter.close()


class TestSpecialEntries:
    async def test_special_files_are_skipped(
        self, server: SftpServer, sftp_root: Path
    ) -> None:
        adapter = make_adapter(server, sftp_root)
        await adapter.write("a.txt", b"a")
        directory = sftp_root / adapter.options.directory.lstrip("/")
        os.mkfifo(directory / "pipe")

        names = {entry.path async for entry in adapter.list("", deep=False)}

        assert names == {"a.txt"}
        with pytest.raises(UnsupportedEntryError):
            await adapter.stat("pipe")
        adapter.close()


class TestEdgeCases:
    async def test_root_contents_can_be_deleted(
        self, server: SftpServer, sftp_root: Path
    ) -> None:
        adapter = make_adapter(server, sftp_root)
        await adapter.write("dir/a.txt", b"a")

        await adapter.delete_directory("")

        assert [entry async for entry in adapter.list("", deep=True)] == []
        assert await adapter.directory_exists("")
        adapter.close()

    def test_refused_rename_is_raised(self, server: SftpServer) -> None:
        class Sftp:
            def posix_rename(self, source: str, target: str) -> None:
                raise PermissionError(errno.EACCES, "denied")

        class Connection:
            active = True
            sftp = Sftp()

        adapter = SftpStorageAdapter(options(server))

        with pytest.raises(PermissionError):
            adapter._replace(Connection(), "a", "b")  # type: ignore[arg-type]


class TestClassify:
    class Connection:
        def __init__(self, *, active: bool) -> None:
            self.active = active

    @pytest.mark.parametrize(
        ("error", "active", "expected"),
        [
            (FileNotFoundError(), True, Failure.KEEP),
            (OSError(errno.EACCES, "denied"), True, Failure.KEEP),
            (OSError("Failure"), True, Failure.KEEP),
            (OSError("Socket is closed"), False, Failure.LOST),
            (EOFError(), True, Failure.LOST),
            (paramiko.SSHException("dropped"), True, Failure.LOST),
            (TimeoutError(), True, Failure.LOST),
            (KeyboardInterrupt(), True, Failure.BROKEN),
        ],
    )
    def test_classify(
        self, error: BaseException, active: bool, expected: Failure
    ) -> None:
        conn = self.Connection(active=active)

        assert classify(error, conn) is expected  # type: ignore[arg-type]

    def test_active(self) -> None:
        client = paramiko.SSHClient()
        conn = SftpConnection(client, None)  # type: ignore[arg-type]

        assert not conn.active
