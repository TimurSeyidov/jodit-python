"""In-process SFTP server over a local directory, for tests."""

import contextlib
import errno
import os
import posixpath
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Self

import paramiko
from paramiko.common import AUTH_FAILED, AUTH_SUCCESSFUL, OPEN_SUCCEEDED
from paramiko.sftp import SFTP_OK, SFTP_OP_UNSUPPORTED

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

USER = "user"
PASSWORD = "secret"  # noqa: S105 - test server


class _Server(paramiko.ServerInterface):
    def __init__(self, client_key: paramiko.PKey | None) -> None:
        self.client_key = client_key

    def check_auth_password(self, username: str, password: str) -> int:
        if (username, password) == (USER, PASSWORD):
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        if username == USER and key == self.client_key:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password,publickey"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return OPEN_SUCCEEDED


def _code(error: OSError) -> int:
    return paramiko.SFTPServer.convert_errno(error.errno or errno.EIO)


def _answer[T](action: Callable[[], T]) -> T | int:
    try:
        return action()
    except OSError as error:
        return _code(error)


def _done(action: Callable[[], object]) -> int:
    try:
        action()
    except OSError as error:
        return _code(error)
    return SFTP_OK


class _Handle(paramiko.SFTPHandle):
    def __init__(self, file: object, flags: int) -> None:
        super().__init__(flags)
        self.file = file

    def stat(self) -> paramiko.SFTPAttributes | int:
        return _answer(
            lambda: paramiko.SFTPAttributes.from_stat(
                os.fstat(self.file.fileno())  # type: ignore[attr-defined]
            )
        )


class LocalSftp(paramiko.SFTPServerInterface):
    """SFTP over ``root``; paths are relative to it, ``/`` is the root."""

    root = Path()
    posix_rename_supported = True

    def canonicalize(self, path: str) -> str:
        return posixpath.normpath(posixpath.join("/", path))

    def _local(self, path: str) -> Path:
        return self.root / self.canonicalize(path).lstrip("/")

    def list_folder(self, path: str) -> list[paramiko.SFTPAttributes] | int:
        def listing() -> list[paramiko.SFTPAttributes]:
            result = []
            for item in self._local(path).iterdir():
                attributes = paramiko.SFTPAttributes.from_stat(item.lstat())
                attributes.filename = item.name
                result.append(attributes)
            return result

        return _answer(listing)

    def stat(self, path: str) -> paramiko.SFTPAttributes | int:
        return _answer(
            lambda: paramiko.SFTPAttributes.from_stat(self._local(path).stat())
        )

    def lstat(self, path: str) -> paramiko.SFTPAttributes | int:
        return _answer(
            lambda: paramiko.SFTPAttributes.from_stat(
                self._local(path).lstat()
            )
        )

    def open(
        self, path: str, flags: int, attr: paramiko.SFTPAttributes
    ) -> paramiko.SFTPHandle | int:
        def opened() -> paramiko.SFTPHandle:
            descriptor = os.open(self._local(path), flags, 0o644)
            if flags & os.O_WRONLY:
                mode = "wb"
            elif flags & os.O_RDWR:
                mode = "r+b"
            else:
                mode = "rb"
            file = os.fdopen(descriptor, mode)
            handle = _Handle(file, flags)
            handle.readfile = file  # type: ignore[attr-defined]
            handle.writefile = file  # type: ignore[attr-defined]
            return handle

        return _answer(opened)

    def remove(self, path: str) -> int:
        return _done(self._local(path).unlink)

    def rename(self, oldpath: str, newpath: str) -> int:
        target = self._local(newpath)
        if target.exists():
            # SFTP v3 rename refuses an existing target.
            return paramiko.SFTPServer.convert_errno(errno.EEXIST)
        return _done(lambda: self._local(oldpath).rename(target))

    def posix_rename(self, oldpath: str, newpath: str) -> int:
        if not self.posix_rename_supported:
            return SFTP_OP_UNSUPPORTED
        return _done(
            lambda: self._local(oldpath).replace(self._local(newpath))
        )

    def mkdir(self, path: str, attr: paramiko.SFTPAttributes) -> int:
        return _done(self._local(path).mkdir)

    def rmdir(self, path: str) -> int:
        return _done(self._local(path).rmdir)


class SftpServer:
    """Accepts SFTP connections on a free local port.

    Args:
        root: Directory served as ``/``.
        posix_rename: Offer the ``posix-rename`` extension.
        client_key: Public key accepted besides the password.
    """

    def __init__(
        self,
        root: Path,
        *,
        posix_rename: bool = True,
        client_key: paramiko.PKey | None = None,
    ) -> None:
        self.host_key = paramiko.ECDSAKey.generate()
        self.client_key = client_key
        self.interface = type(
            "Sftp",
            (LocalSftp,),
            {"root": root, "posix_rename_supported": posix_rename},
        )
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self.listener.getsockname()[1]
        self.transports: list[paramiko.Transport] = []
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)

    @property
    def public_key(self) -> str:
        """Host key as an OpenSSH public key line."""
        return f"{self.host_key.get_name()} {self.host_key.get_base64()}"

    def _accept(self) -> None:
        self.listener.settimeout(0.05)
        while not self._stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            self.accepted += 1
            transport = paramiko.Transport(connection)
            transport.add_server_key(self.host_key)
            transport.set_subsystem_handler(
                "sftp", paramiko.SFTPServer, self.interface
            )
            with contextlib.suppress(paramiko.SSHException, EOFError):
                transport.start_server(server=_Server(self.client_key))
            self.transports.append(transport)

    def drop_connections(self) -> None:
        """Close every open connection from the server side."""
        for transport in self.transports:
            transport.close()

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(5)
        self.listener.close()
        self.drop_connections()


@contextlib.contextmanager
def serving(
    root: Path,
    *,
    posix_rename: bool = True,
    client_key: paramiko.PKey | None = None,
) -> Iterator[SftpServer]:
    """Run a server for the duration of the block.

    Args:
        root: Directory served as ``/``.
        posix_rename: Offer the ``posix-rename`` extension.
        client_key: Public key accepted besides the password.

    Yields:
        The running server.
    """
    with SftpServer(
        root, posix_rename=posix_rename, client_key=client_key
    ) as server:
        yield server
