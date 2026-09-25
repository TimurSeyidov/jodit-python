"""FTP adapter against an in-process pyftpdlib server."""

import ftplib
import logging
import ssl
import threading
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, override

import pytest
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler, TLS_FTPHandler
from pyftpdlib.ioloop import IOLoop
from pyftpdlib.servers import FTPServer

from jcpy.config.models import FtpOptions
from jcpy.storage.ftp import (
    FtpStorageAdapter,
    ListedEntry,
    classify,
    parse_facts,
    parse_list_line,
    parse_listing,
    parse_mlsd,
    parse_time,
)
from jcpy.storage.local import LocalStorageAdapter, UnsupportedEntryError
from jcpy.storage.pool import Failure
from tests.adapter_contract import AdapterContract
from tests.certificates import self_signed_certificate

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

USER = "user"
PASSWORD = "secret"  # noqa: S105 - test server


class LegacyHandler(FTPHandler):  # type: ignore[misc]
    """Server without MLST/MLSD, like vsftpd."""

    proto_cmds: ClassVar = {
        name: value
        for name, value in FTPHandler.proto_cmds.items()
        if name not in {"MLST", "MLSD"}
    }


class StrictRenameHandler(FTPHandler):  # type: ignore[misc]
    """Server refusing to rename over an existing file, like IIS."""

    @override
    def ftp_RNTO(self, path: str) -> None:
        if self.fs.lexists(path):
            self._rnfr = None
            self.respond("553 File exists.")
            return
        super().ftp_RNTO(path)


class NoFeaturesHandler(FTPHandler):  # type: ignore[misc]
    """Server without FEAT: no MLST, MDTM or UTF8 announced."""

    proto_cmds: ClassVar = {
        name: value
        for name, value in FTPHandler.proto_cmds.items()
        if name != "FEAT"
    }


class OddHandler(LegacyHandler):
    """Server answering some commands with unusual errors."""

    @override
    def ftp_RETR(self, file: str) -> None:
        self.respond("553 Not allowed.")

    @override
    def ftp_MDTM(self, path: str) -> None:
        self.respond("550 Not available.")

    @override
    def ftp_LIST(self, path: str) -> None:
        self.respond("552 Listing refused.")


class NoFactsHandler(FTPHandler):  # type: ignore[misc]
    """Server answering MLST oddly: no entry, links, syntax errors."""

    @override
    def ftp_MLST(self, path: str) -> None:
        if path.endswith("link"):
            self.push(
                "250-Listing\r\n type=OS.unix=slink:/x; link\r\n250 End.\r\n"
            )
        elif path.endswith("bad"):
            self.respond("501 Bad path.")
        else:
            self.respond("250 End.")

    @override
    def ftp_MLSD(self, path: str) -> None:
        self.respond("552 Listing refused.")


class NoRenameHandler(FTPHandler):  # type: ignore[misc]
    """Server refusing every rename."""

    @override
    def ftp_RNTO(self, path: str) -> None:
        self._rnfr = None
        self.respond("553 Renaming is not allowed.")


def serve(
    root: Path, handler: type[FTPHandler], **attributes: object
) -> Iterator[int]:
    logging.getLogger("pyftpdlib").setLevel(logging.WARNING)
    authorizer = DummyAuthorizer()
    authorizer.add_user(USER, PASSWORD, str(root), perm="elradfmwMT")
    handler_class = type(
        "Handler", (handler,), {"authorizer": authorizer, **attributes}
    )
    # Each server needs its own loop: the default one is shared.
    server = FTPServer(("127.0.0.1", 0), handler_class, ioloop=IOLoop())
    stop = threading.Event()

    def run() -> None:
        # The loop is stopped and closed in its own thread.
        while not stop.is_set():
            server.serve_forever(
                timeout=0.05, blocking=False, handle_exit=False
            )
        server.close_all()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield server.address[1]
    finally:
        stop.set()
        thread.join(5)


@pytest.fixture(scope="module")
def ftp_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("ftp")


@pytest.fixture(scope="module")
def modern_port(ftp_root: Path) -> Iterator[int]:
    yield from serve(ftp_root, FTPHandler)


@pytest.fixture(scope="module")
def legacy_port(ftp_root: Path) -> Iterator[int]:
    yield from serve(ftp_root, LegacyHandler)


def make_adapter(
    port: int, ftp_root: Path, **values: object
) -> FtpStorageAdapter:
    directory = f"/{uuid.uuid4().hex}"
    (ftp_root / directory[1:]).mkdir()
    options = FtpOptions.model_validate(
        {
            "host": "127.0.0.1",
            "port": port,
            "username": USER,
            "password": PASSWORD,
            "directory": directory,
            **values,
        }
    )
    return FtpStorageAdapter(options)


@pytest.fixture(scope="module")
def strict_port(ftp_root: Path) -> Iterator[int]:
    yield from serve(ftp_root, StrictRenameHandler)


@pytest.fixture(scope="module")
def tls_port(
    ftp_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[int]:
    certificate = self_signed_certificate(tmp_path_factory.mktemp("cert"))
    yield from serve(
        ftp_root,
        TLS_FTPHandler,
        certfile=str(certificate),
        tls_control_required=True,
        tls_data_required=True,
    )


class TestLocalContract(AdapterContract):
    @pytest.fixture
    def adapter(self, tmp_path: Path) -> LocalStorageAdapter:
        return LocalStorageAdapter(tmp_path)


class TestModernServer(AdapterContract):
    @pytest.fixture
    def adapter(
        self, modern_port: int, ftp_root: Path
    ) -> Iterator[FtpStorageAdapter]:
        adapter = make_adapter(modern_port, ftp_root)
        yield adapter
        adapter.close()


class TestLegacyServer(AdapterContract):
    @pytest.fixture
    def adapter(
        self, legacy_port: int, ftp_root: Path
    ) -> Iterator[FtpStorageAdapter]:
        adapter = make_adapter(legacy_port, ftp_root)
        yield adapter
        adapter.close()


class TestStrictRenameServer(AdapterContract):
    @pytest.fixture
    def adapter(
        self, strict_port: int, ftp_root: Path
    ) -> Iterator[FtpStorageAdapter]:
        adapter = make_adapter(strict_port, ftp_root)
        yield adapter
        adapter.close()


class TestTlsServer(AdapterContract):
    @pytest.fixture
    def adapter(
        self, tls_port: int, ftp_root: Path
    ) -> Iterator[FtpStorageAdapter]:
        adapter = make_adapter(
            tls_port, ftp_root, tls=True, verifyCertificate=False
        )
        yield adapter
        adapter.close()


class TestTlsCertificate:
    async def test_untrusted_certificate_is_refused(
        self, tls_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(tls_port, ftp_root, tls=True)

        with pytest.raises(ssl.SSLCertVerificationError):
            await adapter.stat("")

    async def test_plain_login_is_refused(
        self, tls_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(tls_port, ftp_root)

        with pytest.raises(ftplib.error_perm):
            await adapter.stat("")


class TestUnusualServers:
    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        (tmp_path / "dir").mkdir()
        (tmp_path / "a.txt").write_bytes(b"12345")
        return tmp_path

    def adapter(self, port: int) -> FtpStorageAdapter:
        return FtpStorageAdapter(
            FtpOptions.model_validate(
                {
                    "host": "127.0.0.1",
                    "port": port,
                    "username": USER,
                    "password": PASSWORD,
                }
            )
        )

    async def test_server_without_features(self, root: Path) -> None:
        for port in serve(root, NoFeaturesHandler):
            adapter = self.adapter(port)

            file = await adapter.stat("a.txt")
            folder = await adapter.stat("dir")

            assert (file.size, file.last_modified_ms) == (5, 0)
            assert folder.is_directory
            assert await adapter.read("a.txt") == b"12345"
            adapter.close()

    async def test_unusual_errors(self, root: Path) -> None:
        for port in serve(root, OddHandler):
            adapter = self.adapter(port)

            assert (await adapter.stat("a.txt")).last_modified_ms == 0
            with pytest.raises(ftplib.error_perm, match="553"):
                await adapter.read("a.txt")
            with pytest.raises(ftplib.error_perm, match="553"):
                async for _ in adapter.iter_file("a.txt"):
                    pass  # pragma: no cover - fails before the first chunk
            with pytest.raises(ftplib.error_perm, match="552"):
                [e async for e in adapter.list("", deep=False)]
            adapter.close()

    async def test_mlst_without_facts(self, root: Path) -> None:
        for port in serve(root, NoFactsHandler):
            adapter = self.adapter(port)

            with pytest.raises(ftplib.error_reply, match="Unexpected MLST"):
                await adapter.stat("a.txt")
            with pytest.raises(UnsupportedEntryError):
                await adapter.stat("link")
            with pytest.raises(ftplib.error_perm, match="501"):
                await adapter.stat("bad")
            with pytest.raises(ftplib.error_perm, match="552"):
                [e async for e in adapter.list("", deep=False)]
            adapter.close()

    async def test_refused_rename_leaves_no_temporary_file(
        self, root: Path
    ) -> None:
        for port in serve(root, NoRenameHandler):
            adapter = self.adapter(port)

            with pytest.raises(ftplib.error_perm, match="553"):
                await adapter.write("new.txt", b"x")

            assert sorted(path.name for path in root.iterdir()) == [
                "a.txt",
                "dir",
            ]
            adapter.close()

    async def test_symlinks_are_skipped(
        self, root: Path, legacy_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(legacy_port, ftp_root)
        await adapter.write("target.txt", b"x")
        directory = ftp_root / adapter.options.directory.lstrip("/")
        (directory / "link.txt").symlink_to(directory / "target.txt")

        names = {entry.path async for entry in adapter.list("", deep=False)}

        assert names == {"target.txt"}
        adapter.close()

    async def test_listing_a_missing_directory(
        self, legacy_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(legacy_port, ftp_root)

        with pytest.raises(FileNotFoundError):
            async for _ in adapter.list("missing", deep=False):
                pass  # pragma: no cover - fails before the first entry
        adapter.close()

    async def test_root_contents_can_be_deleted(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(modern_port, ftp_root)
        await adapter.write("dir/a.txt", b"a")

        await adapter.delete_directory("")

        assert [entry async for entry in adapter.list("", deep=True)] == []
        assert await adapter.directory_exists("")
        adapter.close()


class TestConnections:
    async def test_login_directory_is_the_default_root(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        options = FtpOptions.model_validate(
            {
                "host": "127.0.0.1",
                "port": modern_port,
                "username": USER,
                "password": PASSWORD,
            }
        )
        adapter = FtpStorageAdapter(options)
        name = f"{uuid.uuid4().hex}.txt"

        await adapter.write(name, b"x")

        assert (ftp_root / name).read_bytes() == b"x"
        adapter.close()

    async def test_connections_are_reused(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(modern_port, ftp_root, connections=1)
        await adapter.write("a.txt", b"a")
        first = adapter._pool._idle[0].connection

        await adapter.read("a.txt")

        assert adapter._pool._idle[0].connection is first
        adapter.close()
        assert adapter._pool._idle == []

    async def test_dropped_connection_is_replaced(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(modern_port, ftp_root, connections=1)
        await adapter.write("a.txt", b"a")
        adapter._pool._idle[0].connection.ftp.sock.close()  # type: ignore[union-attr]

        assert await adapter.read("a.txt") == b"a"
        assert await adapter.stat("a.txt")
        adapter.close()

    async def test_dropped_connection_is_replaced_before_streaming(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(modern_port, ftp_root, connections=1)
        await adapter.write("a.txt", b"a")
        adapter._pool._idle[0].connection.ftp.sock.close()  # type: ignore[union-attr]

        assert [chunk async for chunk in adapter.iter_file("a.txt")] == [b"a"]
        adapter.close()

    async def test_idle_connections_expire(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(modern_port, ftp_root, connections=1)
        await adapter.write("a.txt", b"a")
        first = adapter._pool._idle[0]
        first.since -= adapter.options.idle_timeout + 1

        await adapter.read("a.txt")

        assert adapter._pool._idle[0].connection is not first.connection
        adapter.close()

    async def test_wrong_password(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(modern_port, ftp_root, password="wrong")

        with pytest.raises(ftplib.error_perm, match="530"):
            await adapter.stat("")
        assert adapter._pool._idle == []

    async def test_tls_needs_a_server_that_speaks_it(
        self, modern_port: int, ftp_root: Path
    ) -> None:
        adapter = make_adapter(
            modern_port, ftp_root, tls=True, verifyCertificate=False
        )

        with pytest.raises(ftplib.Error):
            await adapter.stat("")


class TestParsing:
    def test_parse_time(self) -> None:
        expected = datetime(2026, 9, 25, 12, 34, 56, tzinfo=UTC).timestamp()

        assert parse_time("20260925123456") == expected * 1000
        assert parse_time("20260925123456.5") == expected * 1000 + 500
        assert parse_time("garbage") is None

    def test_parse_facts(self) -> None:
        assert parse_facts(
            "type=file;size=12;modify=20260925123456; a b.txt"
        ) == (
            ListedEntry(
                "a b.txt",
                "file",
                12,
                datetime(2026, 9, 25, 12, 34, 56, tzinfo=UTC).timestamp()
                * 1000,
            )
        )
        assert parse_facts("Type=cdir; /x").kind == "dir"
        assert parse_facts("type=OS.unix=slink:/y; y").kind == "other"

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            (
                "-rw-r--r--  1 ftp  ftp        1234 Sep 20 10:05 a b.txt",
                ListedEntry(
                    "a b.txt",
                    "file",
                    1234,
                    datetime(2026, 9, 20, 10, 5, tzinfo=UTC).timestamp()
                    * 1000,
                ),
            ),
            (
                "drwxr-xr-x  2 ftp  ftp        4096 Dec 31  2025 folder",
                ListedEntry(
                    "folder",
                    "dir",
                    None,
                    datetime(2025, 12, 31, tzinfo=UTC).timestamp() * 1000,
                ),
            ),
            (
                "-rw-r--r--    1 ftp      ftp             1 Dec 31 23:00 old",
                ListedEntry(
                    "old",
                    "file",
                    1,
                    datetime(2025, 12, 31, 23, tzinfo=UTC).timestamp() * 1000,
                ),
            ),
            (
                "lrwxrwxrwx  1 ftp  ftp           3 Sep 20 10:05 l -> x",
                ListedEntry(
                    "l",
                    "other",
                    None,
                    datetime(2026, 9, 20, 10, 5, tzinfo=UTC).timestamp()
                    * 1000,
                ),
            ),
            (
                "09-20-26  10:05PM       <DIR>          My Folder",
                ListedEntry(
                    "My Folder",
                    "dir",
                    None,
                    datetime(2026, 9, 20, 22, 5, tzinfo=UTC).timestamp()
                    * 1000,
                ),
            ),
            (
                "12-01-1999  12:00AM              42 old.txt",
                ListedEntry(
                    "old.txt",
                    "file",
                    42,
                    datetime(1999, 12, 1, 0, 0, tzinfo=UTC).timestamp() * 1000,
                ),
            ),
            ("total 8", None),
            ("drwxr-xr-x 2 ftp ftp 4096 Sep 20 10:05 .", None),
        ],
    )
    def test_parse_list_line(
        self, line: str, expected: ListedEntry | None
    ) -> None:
        now = datetime(2026, 9, 25, tzinfo=UTC)

        assert parse_list_line(line, now) == expected

    def test_parse_mlsd(self) -> None:
        items = [
            (".", {"type": "cdir"}),
            ("..", {"type": "pdir"}),
            ("x", {"type": "cdir"}),
            ("a.txt", {"type": "file", "size": "3"}),
            ("sub", {"type": "dir"}),
        ]

        assert parse_mlsd(items) == [
            ListedEntry("a.txt", "file", 3),
            ListedEntry("sub", "dir"),
        ]

    def test_parse_listing(self) -> None:
        lines = ["total 4", "-rw-r--r-- 1 u g 3 Sep 20 2026 a.txt"]

        assert [entry.name for entry in parse_listing(lines)] == ["a.txt"]

    @pytest.mark.parametrize(
        "line",
        [
            "-rw-r--r-- 1 ftp ftp 1 Foo 20 10:05 bad-month",
            "-rw-r--r-- 1 ftp ftp 1 Feb 31 10:05 bad-day",
            "13-45-26  10:05PM  1 bad-date",
        ],
    )
    def test_unparsable_dates(self, line: str) -> None:
        entry = parse_list_line(line)

        assert entry is not None
        assert entry.last_modified_ms is None

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (ftplib.error_temp("421 Timeout"), Failure.LOST),
            (ftplib.error_temp("450 Busy"), Failure.KEEP),
            (ftplib.error_perm("550 No such file"), Failure.KEEP),
            (EOFError(), Failure.LOST),
            (ConnectionResetError(), Failure.LOST),
            (TimeoutError(), Failure.LOST),
            (FileNotFoundError(), Failure.KEEP),
            (OSError("bad"), Failure.BROKEN),
            (ftplib.error_reply("bad"), Failure.BROKEN),
            (ValueError("bad"), Failure.KEEP),
            (KeyboardInterrupt(), Failure.BROKEN),
        ],
    )
    def test_classify(self, error: BaseException, expected: Failure) -> None:
        assert classify(error) is expected
