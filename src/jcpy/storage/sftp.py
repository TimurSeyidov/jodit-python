"""Storage adapter for SFTP (SSH) servers."""

import base64
import contextlib
import logging
import stat as stat_module
import tempfile
import uuid
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import TYPE_CHECKING

import paramiko

from jcpy.storage.base import CHUNK_SIZE, FileWasNotFoundError, StatEntry
from jcpy.storage.local import UnsupportedEntryError
from jcpy.storage.pool import (
    ConnectionPool,
    Failure,
    remote_path,
    replace_by_swap,
)
from jcpy.storage.threads import TransferThreads

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator
    from typing import BinaryIO

    from jcpy.config.models import SftpOptions

logger = logging.getLogger("jcpy")

SPOOL_SIZE = 1024 * 1024
"""Bytes of a copied file kept in memory before spilling to disk."""

PREFETCH_LIMIT = 8 * 1024 * 1024
"""Largest file read ahead in parallel requests when streamed."""

_KEY_TYPES: tuple[type[paramiko.PKey], ...] = (
    paramiko.Ed25519Key,
    paramiko.ECDSAKey,
    paramiko.RSAKey,
)


class HostKeyError(ValueError):
    """A ``hostKey`` option is not an OpenSSH public key line."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f'hostKey must look like "ssh-ed25519 AAAA...", got "{value[:40]}"'
        )


def parse_host_key(value: str) -> paramiko.PKey:
    """Parse a public key as printed by ``ssh-keyscan`` or ``.pub`` files.

    Args:
        value: ``[host] type base64 [comment]``.

    Returns:
        The key.

    Raises:
        HostKeyError: The value is not a public key.
    """
    parts = value.split()
    for index, part in enumerate(parts[:2]):
        if part.startswith(("ssh-", "ecdsa-", "sk-")) and index + 1 < len(
            parts
        ):
            try:
                data = base64.b64decode(parts[index + 1], validate=True)
                return paramiko.PKey.from_type_string(part, data)
            except ValueError, paramiko.SSHException:
                break
    raise HostKeyError(value)


def load_private_key(text: str, passphrase: str | None) -> paramiko.PKey:
    """Load a private key in OpenSSH or PEM format.

    Args:
        text: Key file contents.
        passphrase: Passphrase of an encrypted key.

    Returns:
        The key.

    Raises:
        paramiko.SSHException: The text is not a supported key or the
            passphrase is wrong.
    """
    error: paramiko.SSHException | None = None
    for key_type in _KEY_TYPES:
        try:
            return key_type.from_private_key(StringIO(text), passphrase)
        except paramiko.SSHException as problem:
            error = problem
    raise error or paramiko.SSHException("Unsupported private key")


@dataclass(slots=True)
class SftpConnection:
    """Authenticated SSH session with an SFTP channel.

    Attributes:
        client: SSH client.
        sftp: SFTP client on it.
    """

    client: paramiko.SSHClient
    sftp: paramiko.SFTPClient

    @property
    def active(self) -> bool:
        """Whether the SSH transport is still connected."""
        transport = self.client.get_transport()
        return transport is not None and transport.is_active()


def classify(error: BaseException, conn: SftpConnection) -> Failure:
    """Tell what an exception means for the SFTP connection it came from.

    Args:
        error: Exception raised by an operation.
        conn: Connection it was raised with.

    Returns:
        ``LOST`` when the transport is gone, ``KEEP`` for refused
        requests and adapter errors, ``BROKEN`` for interruptions.
    """
    if not isinstance(error, Exception):
        return Failure.BROKEN
    if not conn.active or isinstance(
        error,
        EOFError | ConnectionError | TimeoutError | paramiko.SSHException,
    ):
        return Failure.LOST
    return Failure.KEEP


class SftpStorageAdapter:
    """Storage adapter for a directory on an SFTP server.

    The server's host key is always checked: against ``hostKey``,
    ``knownHostsFile`` or the system ``known_hosts``; unknown keys are
    rejected. Writes go to a temporary file renamed over the target
    (``posix-rename`` when the server has it).

    Args:
        options: SFTP settings.
    """

    def __init__(self, options: SftpOptions) -> None:
        self.options = options
        self._private_key: paramiko.PKey | None = None
        if options.private_key is not None:
            self._private_key = load_private_key(
                options.private_key, options.passphrase
            )
        self._host_keys: builtins.list[paramiko.PKey] = []
        host_keys = options.host_key
        if isinstance(host_keys, str):
            host_keys = [host_keys]
        for value in host_keys or ():
            self._host_keys.append(parse_host_key(value))
        self._transfers = TransferThreads()
        self._pool = ConnectionPool(
            self._connect,
            _close,
            classify,
            size=options.connections,
            idle_timeout=options.idle_timeout,
        )

    def close(self) -> None:
        """Close the idle connections."""
        self._pool.close()

    def _remote(self, path: str) -> str:
        return remote_path(self.options.directory, path)

    def _connect(self) -> SftpConnection:
        options = self.options
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        if self._host_keys:
            name = (
                options.host
                if options.port == 22
                else f"[{options.host}]:{options.port}"
            )
            known = client.get_host_keys()
            for key in self._host_keys:
                known.add(name, key.get_name(), key)
        elif options.known_hosts_file is not None:
            client.load_host_keys(options.known_hosts_file)
        else:
            client.load_system_host_keys()
        try:
            client.connect(
                options.host,
                port=options.port,
                username=options.username,
                password=options.password,
                pkey=self._private_key,
                key_filename=options.private_key_file,
                passphrase=options.passphrase,
                timeout=options.timeout,
                banner_timeout=options.timeout,
                auth_timeout=options.timeout,
                channel_timeout=options.timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            sftp = client.open_sftp()
            sftp.get_channel().settimeout(options.timeout)  # type: ignore[union-attr]
        except BaseException:
            client.close()
            raise
        return SftpConnection(client, sftp)

    # --- blocking helpers, run with a pooled connection ------------------

    @staticmethod
    def _entry(path: str, attributes: paramiko.SFTPAttributes) -> StatEntry:
        mode = attributes.st_mode or 0
        modified = (attributes.st_mtime or 0) * 1000
        if stat_module.S_ISREG(mode):
            return StatEntry(
                path,
                is_file=True,
                size=attributes.st_size or 0,
                last_modified_ms=modified,
            )
        if stat_module.S_ISDIR(mode):
            return StatEntry(path, is_file=False, last_modified_ms=modified)
        raise UnsupportedEntryError

    def _stat(self, conn: SftpConnection, path: str) -> StatEntry:
        return self._entry(path, conn.sftp.stat(self._remote(path)))

    @staticmethod
    def _mode_at(conn: SftpConnection, remote: str) -> int | None:
        try:
            return conn.sftp.stat(remote).st_mode or 0
        except FileNotFoundError:
            return None

    def _exists(self, conn: SftpConnection, path: str) -> StatEntry | None:
        try:
            return self._stat(conn, path)
        except FileNotFoundError:
            return None

    def _scan(
        self, conn: SftpConnection, path: str, deep: bool
    ) -> builtins.list[StatEntry]:
        result: builtins.list[StatEntry] = []
        pending = [path]
        while pending:
            current = pending.pop(0)
            for item in conn.sftp.listdir_attr(self._remote(current)):
                relative = (
                    f"{current}/{item.filename}" if current else item.filename
                )
                try:
                    entry = self._entry(relative, item)
                except UnsupportedEntryError:
                    logger.warning(
                        "Skipping %s: not a regular file or directory",
                        relative,
                    )
                    continue
                result.append(entry)
                if deep and entry.is_directory:
                    pending.append(relative)
        return result

    def _make_directories(self, conn: SftpConnection, path: str) -> None:
        if not path:
            return
        try:
            conn.sftp.mkdir(self._remote(path))
        except OSError:
            parts = path.split("/")
            for index in range(1, len(parts) + 1):
                with contextlib.suppress(OSError):
                    conn.sftp.mkdir(self._remote("/".join(parts[:index])))
            entry = self._exists(conn, path)
            if entry is None or entry.is_file:
                raise

    def _make_parents(self, conn: SftpConnection, path: str) -> None:
        self._make_directories(conn, path.rpartition("/")[0])

    def _replace(self, conn: SftpConnection, source: str, target: str) -> None:
        """Rename an existing file ``source`` to ``target``.

        Without ``posix-rename`` a file at ``target`` is moved aside
        first and put back if the rename still fails, so it is never
        lost; any other target (a directory) fails the rename.
        """
        try:
            conn.sftp.posix_rename(source, target)
        except OSError as error:
            if not conn.active or error.errno is not None:
                raise
            mode = self._mode_at(conn, target)
            if mode is None:
                conn.sftp.rename(source, target)
            elif stat_module.S_ISREG(mode):
                replace_by_swap(
                    conn.sftp.rename, conn.sftp.remove, source, target
                )
            else:
                raise

    def _store(
        self, conn: SftpConnection, path: str, file: BinaryIO, start: int
    ) -> None:
        remote = self._remote(path)
        directory, slash, _ = remote.rpartition("/")
        temporary = f"{directory}{slash}.{uuid.uuid4().hex}.tmp"

        def upload() -> None:
            file.seek(start)
            conn.sftp.putfo(file, temporary)

        try:
            try:
                upload()
            except FileNotFoundError:
                self._make_parents(conn, path)
                upload()
            self._replace(conn, temporary, remote)
        except BaseException:
            with contextlib.suppress(Exception):
                conn.sftp.remove(temporary)
            raise

    def _retrieve(
        self, conn: SftpConnection, path: str, sink: BinaryIO
    ) -> None:
        try:
            conn.sftp.getfo(self._remote(path), sink)
        except FileNotFoundError:
            raise FileWasNotFoundError(path) from None

    def _read(self, conn: SftpConnection, path: str) -> bytes:
        sink = BytesIO()
        self._retrieve(conn, path, sink)
        return sink.getvalue()

    def _copy(
        self, conn: SftpConnection, source: str, destination: str
    ) -> None:
        with tempfile.SpooledTemporaryFile(max_size=SPOOL_SIZE) as spool:
            buffer: BinaryIO = spool  # type: ignore[assignment]
            self._retrieve(conn, source, buffer)
            self._store(conn, destination, buffer, 0)

    def _delete_file(self, conn: SftpConnection, path: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            conn.sftp.remove(self._remote(path))

    def _delete_directory(self, conn: SftpConnection, path: str) -> None:
        entry = self._exists(conn, path)
        if entry is None:
            return
        if entry.is_file:
            conn.sftp.remove(self._remote(path))
            return
        entries = self._scan(conn, path, deep=True)
        for item in entries:
            if item.is_file:
                conn.sftp.remove(self._remote(item.path))
        folders = sorted(
            (item.path for item in entries if item.is_directory),
            key=lambda folder: folder.count("/"),
            reverse=True,
        )
        for folder in folders:
            conn.sftp.rmdir(self._remote(folder))
        if path:
            conn.sftp.rmdir(self._remote(path))

    def _move(
        self, conn: SftpConnection, source: str, destination: str
    ) -> None:
        origin = self._stat(conn, source)
        self._make_parents(conn, destination)
        remote, target = self._remote(source), self._remote(destination)
        if origin.is_file:
            self._replace(conn, remote, target)
        else:
            conn.sftp.rename(remote, target)

    def _open(self, conn: SftpConnection, path: str) -> paramiko.SFTPFile:
        try:
            handle = conn.sftp.open(self._remote(path), "rb")
        except FileNotFoundError:
            raise FileWasNotFoundError(path) from None
        size = handle.stat().st_size or 0
        if size <= PREFETCH_LIMIT:
            handle.prefetch(size)
        return handle

    # --- StorageAdapter ---------------------------------------------------

    async def write(self, path: str, contents: bytes) -> None:
        """Create or replace a file, creating parent directories.

        Args:
            path: File path.
            contents: File contents.
        """
        await self.write_file(path, BytesIO(contents))

    async def write_file(self, path: str, file: BinaryIO) -> None:
        """Upload a file from a readable binary file.

        The contents go to a temporary file in the target directory that
        is then renamed over the target.

        Args:
            path: File path.
            file: Source positioned at the start of the contents.
        """
        start = file.tell()
        await self._pool.run(
            lambda conn: self._store(conn, path, file, start),
            threads=self._transfers,
        )

    async def iter_file(self, path: str) -> AsyncIterator[bytes]:
        """Download a file in chunks.

        Files up to ``PREFETCH_LIMIT`` are requested ahead in parallel;
        larger ones are read one chunk at a time.

        Args:
            path: File path.

        Yields:
            Chunks of at most ``CHUNK_SIZE`` bytes.

        Raises:
            FileWasNotFoundError: The file does not exist.
        """
        async with self._pool.hold(_probe) as conn:
            handle = await self._transfers.run(self._open, conn, path)
            try:
                while chunk := await self._transfers.run(
                    handle.read, CHUNK_SIZE
                ):
                    yield chunk
            finally:
                await self._transfers.run(handle.close)

    async def read(self, path: str) -> bytes:
        """Download a whole file.

        Args:
            path: File path.

        Returns:
            File contents.

        Raises:
            FileWasNotFoundError: The file does not exist.
        """
        return await self._pool.run(
            lambda conn: self._read(conn, path), threads=self._transfers
        )

    async def delete_file(self, path: str) -> None:
        """Delete a file; a missing file is not an error.

        Args:
            path: File path.
        """
        await self._pool.run(lambda conn: self._delete_file(conn, path))

    async def create_directory(self, path: str) -> None:
        """Create a directory with its missing parents.

        Args:
            path: Directory path.
        """
        await self._pool.run(lambda conn: self._make_directories(conn, path))

    async def delete_directory(self, path: str) -> None:
        """Delete a directory recursively; missing is not an error.

        Args:
            path: Directory path.
        """
        await self._pool.run(lambda conn: self._delete_directory(conn, path))

    async def stat(self, path: str) -> StatEntry:
        """Read metadata of a file or directory (following symlinks).

        Args:
            path: Entry path.

        Returns:
            Metadata with size and modification time.

        Raises:
            FileNotFoundError: The entry does not exist.
        """
        return await self._pool.run(lambda conn: self._stat(conn, path))

    async def list(self, path: str, *, deep: bool) -> AsyncIterator[StatEntry]:
        """List a directory.

        Args:
            path: Directory path.
            deep: Include nested entries.

        Yields:
            Entries in server order, with size and time; links and
            other entries are skipped.
        """
        entries = await self._pool.run(
            lambda conn: self._scan(conn, path, deep)
        )
        for entry in entries:
            yield entry

    async def file_exists(self, path: str) -> bool:
        """Tell whether a file exists.

        Args:
            path: File path.

        Returns:
            ``True`` for an existing file (not a directory).
        """
        entry = await self._pool.run(lambda conn: self._exists(conn, path))
        return entry is not None and entry.is_file

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a directory exists.

        Args:
            path: Directory path.

        Returns:
            ``True`` for an existing directory (the root included).
        """
        entry = await self._pool.run(lambda conn: self._exists(conn, path))
        return entry is not None and entry.is_directory

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy a file through the connector (SFTP has no server copy).

        Args:
            source: Existing file path.
            destination: New file path.
        """
        await self._pool.run(
            lambda conn: self._copy(conn, source, destination),
            threads=self._transfers,
        )

    async def move_file(self, source: str, destination: str) -> None:
        """Rename a file or directory, creating destination parents.

        Args:
            source: Existing path.
            destination: New path.
        """
        await self._pool.run(
            lambda conn: self._move(conn, source, destination)
        )


def _probe(conn: SftpConnection) -> None:
    conn.sftp.normalize(".")


def _close(conn: SftpConnection) -> None:
    conn.sftp.close()
    conn.client.close()
