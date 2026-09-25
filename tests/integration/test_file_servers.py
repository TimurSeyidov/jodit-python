"""FTP and SFTP adapters against real servers in Docker.

vsftpd (plain and FTPS, no MLSD) and OpenSSH; skipped when no Docker
daemon is reachable.
"""

import ftplib
import os
import random
import socket
import time
import uuid
from typing import TYPE_CHECKING

import paramiko
import pytest
from docker.errors import DockerException
from testcontainers.core.container import DockerContainer

from jcpy.config.models import FtpOptions, SftpOptions
from jcpy.storage.ftp import FtpStorageAdapter
from jcpy.storage.sftp import SftpStorageAdapter
from tests.adapter_contract import AdapterContract
from tests.certificates import self_signed_certificate
from tests.conftest import make_app, open_client
from tests.docker import docker_available

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from pathlib import Path

    from jcpy.types import JsonObject

USER = "user"
PASSWORD = "secret"  # noqa: S105 - test server
FTP_IMAGE = os.environ.get("FTP_IMAGE", "delfer/alpine-ftp-server:latest")
SFTP_IMAGE = os.environ.get("SFTP_IMAGE", "atmoz/sftp:alpine")
PASSIVE_PORTS = 6

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not docker_available(), reason="Docker is not available"
    ),
]


def wait_for(check: Callable[[], object], what: str) -> None:
    deadline = time.monotonic() + 60
    while True:
        try:
            check()
        except OSError, EOFError, ftplib.Error, paramiko.SSHException:
            if time.monotonic() > deadline:
                pytest.fail(f"{what} did not start")
            time.sleep(0.5)
        else:
            return


def free_port_range(size: int) -> int:
    """First port of ``size`` consecutive free ports."""
    for _ in range(50):
        first = random.randint(30000, 60000 - size)  # noqa: S311 - not crypto
        try:
            for port in range(first, first + size):
                # Docker publishes on every interface, IPv4 and IPv6.
                with socket.create_server(
                    ("", port),
                    family=socket.AF_INET6,
                    dualstack_ipv6=socket.has_dualstack_ipv6(),
                ):
                    pass
        except OSError:
            continue
        return first
    pytest.fail("no free passive port range")


def vsftpd_container(certificate: Path | None, first: int) -> DockerContainer:
    container = (
        DockerContainer(FTP_IMAGE)
        .with_env("USERS", f"{USER}|{PASSWORD}")
        .with_env("MIN_PORT", str(first))
        .with_env("MAX_PORT", str(first + PASSIVE_PORTS - 1))
        .with_exposed_ports(21)
    )
    for port in range(first, first + PASSIVE_PORTS):
        container = container.with_bind_ports(port, port)
    if certificate is not None:
        container = (
            container.with_volume_mapping(
                str(certificate.parent), "/certs", "ro"
            )
            .with_env("TLS_CERT", "/certs/server.pem")
            .with_env("TLS_KEY", "/certs/server.pem")
        )
    return container


def start_vsftpd(certificate: Path | None) -> DockerContainer:
    # Passive ports are published one to one: the client ignores the
    # address vsftpd announces and connects to the published host.
    # Docker may still hold ports of a container that just stopped, so
    # a busy range is replaced by another one.
    for _ in range(5):
        container = vsftpd_container(
            certificate, free_port_range(PASSIVE_PORTS)
        )
        try:
            container.start()
        except DockerException as error:
            container.stop()
            if "address already in use" not in str(error):
                raise
            continue
        return container
    pytest.fail("no passive port range could be published")


def vsftpd(certificate: Path | None) -> Iterator[tuple[str, int]]:
    container = start_vsftpd(certificate)
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(21))

        def login() -> None:
            ftp = ftplib.FTP_TLS() if certificate else ftplib.FTP()
            try:
                ftp.connect(host, port, timeout=5)
                ftp.login(USER, PASSWORD)
            finally:
                ftp.close()

        wait_for(login, "vsftpd")
        yield host, port
    finally:
        container.stop()


@pytest.fixture(scope="module")
def ftp_server() -> Iterator[tuple[str, int]]:
    yield from vsftpd(None)


@pytest.fixture(scope="module")
def ftps_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, int]]:
    certificate = self_signed_certificate(tmp_path_factory.mktemp("cert"))
    certificate.chmod(0o644)
    certificate.parent.chmod(0o755)
    yield from vsftpd(certificate)


@pytest.fixture(scope="module")
def sftp_server() -> Iterator[tuple[str, int, str]]:
    container = (
        DockerContainer(SFTP_IMAGE)
        .with_command(f"{USER}:{PASSWORD}:::upload")
        .with_exposed_ports(22)
    )
    with container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(22))
        keys: list[str] = []

        def scan() -> None:
            # What ssh-keyscan does: read the key the server presents.
            with socket.create_connection((host, port), timeout=5) as sock:
                transport = paramiko.Transport(sock)
                try:
                    transport.start_client(timeout=5)
                    key = transport.get_remote_server_key()
                finally:
                    transport.close()
            keys.append(f"{key.get_name()} {key.get_base64()}")

        wait_for(scan, "OpenSSH")
        yield host, port, keys[-1]


async def isolated_ftp(
    server: tuple[str, int], **values: object
) -> FtpStorageAdapter:
    """Adapter rooted in a new folder of the login directory."""
    host, port = server
    options = FtpOptions.model_validate(
        {
            "host": host,
            "port": port,
            "username": USER,
            "password": PASSWORD,
            **values,
        }
    )
    directory = uuid.uuid4().hex
    setup = FtpStorageAdapter(options)
    await setup.create_directory(directory)
    setup.close()
    return FtpStorageAdapter(
        options.model_copy(update={"directory": directory})
    )


def sftp_options(
    server: tuple[str, int, str], directory: str = "upload"
) -> SftpOptions:
    host, port, key = server
    return SftpOptions.model_validate(
        {
            "host": host,
            "port": port,
            "username": USER,
            "password": PASSWORD,
            "hostKey": key,
            "directory": directory,
        }
    )


async def isolated_sftp(server: tuple[str, int, str]) -> SftpStorageAdapter:
    """Adapter rooted in a new folder of the writable ``upload``."""
    directory = uuid.uuid4().hex
    setup = SftpStorageAdapter(sftp_options(server))
    await setup.create_directory(directory)
    setup.close()
    return SftpStorageAdapter(sftp_options(server, f"upload/{directory}"))


class TestVsftpd(AdapterContract):
    @pytest.fixture
    async def adapter(
        self, ftp_server: tuple[str, int]
    ) -> AsyncIterator[FtpStorageAdapter]:
        adapter = await isolated_ftp(ftp_server)
        yield adapter
        adapter.close()


class TestVsftpdTls(AdapterContract):
    @pytest.fixture
    async def adapter(
        self, ftps_server: tuple[str, int]
    ) -> AsyncIterator[FtpStorageAdapter]:
        adapter = await isolated_ftp(
            ftps_server, tls=True, verifyCertificate=False
        )
        yield adapter
        adapter.close()


class TestOpenSsh(AdapterContract):
    @pytest.fixture
    async def adapter(
        self, sftp_server: tuple[str, int, str]
    ) -> AsyncIterator[SftpStorageAdapter]:
        adapter = await isolated_sftp(sftp_server)
        yield adapter
        adapter.close()


class TestConnector:
    @pytest.mark.parametrize("adapter_name", ["ftp", "sftp"])
    async def test_upload_list_and_download(
        self,
        adapter_name: str,
        ftp_server: tuple[str, int],
        sftp_server: tuple[str, int, str],
    ) -> None:
        if adapter_name == "ftp":
            adapter: (
                FtpStorageAdapter | SftpStorageAdapter
            ) = await isolated_ftp(ftp_server)
        else:
            adapter = await isolated_sftp(sftp_server)
        options = adapter.options.model_dump(by_alias=True)
        adapter.close()
        config: JsonObject = {
            "sources": {
                "server": {
                    "title": "Server",
                    "baseurl": "https://www.example.com/uploads/",
                    "storageAdapter": adapter_name,
                    adapter_name: options,
                }
            }
        }

        async with open_client(make_app(config)) as http:
            uploaded = await http.post(
                "/fileUpload",
                data={"source": "server", "path": "/"},
                files={"files[0]": ("note.txt", b"hello", "text/plain")},
            )
            listed = await http.post("/files", json={"source": "server"})
            downloaded = await http.get(
                "/fileDownload",
                params={"source": "server", "name": "note.txt"},
            )

        assert uploaded.status_code == 200, uploaded.text
        files = listed.json()["data"]["sources"][0]["files"]
        assert [item["file"] for item in files] == ["note.txt"]
        assert downloaded.content == b"hello"
