"""Storage adapter for FTP and FTPS (explicit TLS) servers."""

import contextlib
import ftplib
import logging
import re
import ssl
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING

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
    import socket
    from collections.abc import AsyncIterator, Iterable
    from typing import BinaryIO

    from jcpy.config.models import FtpOptions

logger = logging.getLogger("jcpy")

SPOOL_SIZE = 1024 * 1024
"""Bytes of a copied file kept in memory before spilling to disk."""

_UNIX_LINE = re.compile(
    r"^(?P<mode>[-dl])\S*\s+\S+\s+\S+\s+\S+\s+(?P<size>\d+)\s+"
    r"(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+"
    r"(?:(?P<hour>\d{1,2}):(?P<minute>\d{2})|(?P<year>\d{4}))\s"
    r"(?P<name>.+)$"
)
_DOS_LINE = re.compile(
    r"^(?P<month>\d{2})-(?P<day>\d{2})-(?P<year>\d{2,4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?P<half>[AP]M)\s+"
    r"(?:(?P<dir><DIR>)|(?P<size>\d+))\s+(?P<name>.+)$"
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        start=1,
    )
}


@dataclass(frozen=True, slots=True)
class ListedEntry:
    """Entry parsed from a directory listing.

    Attributes:
        name: Entry name.
        kind: ``"file"``, ``"dir"`` or ``"other"`` (links, devices).
        size: Size in bytes of a file.
        last_modified_ms: Modification time in epoch milliseconds.
    """

    name: str
    kind: str
    size: int | None = None
    last_modified_ms: float | None = None


def parse_time(value: str) -> float | None:
    """Parse an FTP timestamp (``MDTM``, ``MLST``) as UTC.

    Args:
        value: ``YYYYMMDDHHMMSS`` with optional fractional seconds.

    Returns:
        Epoch milliseconds, or ``None`` when malformed.
    """
    whole, _, fraction = value.strip().partition(".")
    try:
        moment = datetime.strptime(whole, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    milliseconds = int((fraction + "000")[:3]) if fraction.isdigit() else 0
    return moment.timestamp() * 1000 + milliseconds


def parse_facts(line: str) -> ListedEntry:
    """Parse one ``MLST``/``MLSD`` entry.

    Args:
        line: ``fact=value;...; name``.

    Returns:
        The entry; ``cdir``/``pdir`` count as directories.
    """
    facts_text, _, name = line.partition(" ")
    facts: dict[str, str] = {}
    for fact in facts_text.split(";"):
        key, _, value = fact.partition("=")
        if key:
            facts[key.lower()] = value
    return _from_facts(name, facts)


def _from_facts(name: str, facts: dict[str, str]) -> ListedEntry:
    kind = facts.get("type", "").lower()
    kind = {"file": "file", "dir": "dir", "cdir": "dir", "pdir": "dir"}.get(
        kind, "other"
    )
    size = facts.get("size")
    modify = facts.get("modify")
    return ListedEntry(
        name=name,
        kind=kind,
        size=int(size) if kind == "file" and size and size.isdigit() else None,
        last_modified_ms=parse_time(modify) if modify else None,
    )


def parse_mlsd(
    items: Iterable[tuple[str, dict[str, str]]],
) -> list[ListedEntry]:
    """Turn ``MLSD`` entries into listing entries.

    Args:
        items: Names with their facts, as ``ftplib.FTP.mlsd`` yields them.

    Returns:
        Entries without the directory itself and its parent.
    """
    return [
        _from_facts(name, facts)
        for name, facts in items
        if name not in {".", ".."}
        and facts.get("type", "").lower() not in {"cdir", "pdir"}
    ]


def parse_listing(
    lines: Iterable[str], now: datetime | None = None
) -> list[ListedEntry]:
    """Parse a ``LIST`` answer.

    Args:
        lines: Answer lines.
        now: Current time, for the year of recent Unix entries.

    Returns:
        Entries of the lines that are entries.
    """
    moment = now or _now()
    return [
        entry
        for line in lines
        if (entry := parse_list_line(line, moment)) is not None
    ]


def parse_list_line(
    line: str, now: datetime | None = None
) -> ListedEntry | None:
    """Parse one line of a ``LIST`` answer (Unix or DOS style).

    Unix times without a year are the latest such date not after
    tomorrow; times are taken as UTC.

    Args:
        line: Listing line.
        now: Current time, for the year of recent Unix entries.

    Returns:
        The entry, or ``None`` for lines that are not entries
        (``total``, ``.``, ``..``, unknown formats).
    """
    match = _UNIX_LINE.match(line)
    if match is not None:
        kind = {"-": "file", "d": "dir"}.get(match["mode"], "other")
        name = match["name"]
        if kind == "other" and " -> " in name:
            name = name.split(" -> ", 1)[0]
        return _entry(
            name, kind, match["size"], _unix_time(match, now or _now())
        )
    match = _DOS_LINE.match(line)
    if match is not None:
        kind = "dir" if match["dir"] else "file"
        return _entry(match["name"], kind, match["size"], _dos_time(match))
    return None


def _now() -> datetime:
    return datetime.now(UTC)


def _entry(
    name: str, kind: str, size: str | None, moment: datetime | None
) -> ListedEntry | None:
    if name in {".", ".."}:
        return None
    return ListedEntry(
        name=name,
        kind=kind,
        size=int(size) if kind == "file" and size else None,
        last_modified_ms=moment.timestamp() * 1000 if moment else None,
    )


def _unix_time(match: re.Match[str], now: datetime) -> datetime | None:
    month = _MONTHS.get(match["month"].lower())
    if month is None:
        return None
    day = int(match["day"])
    try:
        if match["year"]:
            return datetime(int(match["year"]), month, day, tzinfo=UTC)
        hour, minute = int(match["hour"]), int(match["minute"])
        moment = datetime(now.year, month, day, hour, minute, tzinfo=UTC)
        if (moment - now).days >= 1:
            moment = moment.replace(year=now.year - 1)
    except ValueError:
        return None
    return moment


def _dos_time(match: re.Match[str]) -> datetime | None:
    year = int(match["year"])
    if year < 100:
        year += 2000 if year < 70 else 1900
    hour = int(match["hour"]) % 12 + (12 if match["half"] == "PM" else 0)
    try:
        return datetime(
            year,
            int(match["month"]),
            int(match["day"]),
            hour,
            int(match["minute"]),
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _code(error: BaseException) -> str:
    return str(error)[:3]


def _is_missing(error: ftplib.Error) -> bool:
    return isinstance(error, ftplib.error_perm) and _code(error) == "550"


def classify(error: BaseException) -> Failure:
    """Tell what an exception means for the FTP connection it came from.

    Args:
        error: Exception raised by an operation.

    Returns:
        ``LOST`` for dropped connections (EOF, resets, timeouts, ``421``),
        ``KEEP`` for refused commands and adapter errors, ``BROKEN``
        otherwise.
    """
    if isinstance(error, ftplib.error_temp):
        return Failure.LOST if _code(error) == "421" else Failure.KEEP
    if isinstance(error, ftplib.error_perm):
        return Failure.KEEP
    if isinstance(error, EOFError | ConnectionError | TimeoutError):
        return Failure.LOST
    if isinstance(
        error, FileNotFoundError | FileExistsError | UnsupportedEntryError
    ):
        return Failure.KEEP
    if isinstance(error, OSError | ftplib.Error):
        return Failure.BROKEN
    if isinstance(error, Exception):
        return Failure.KEEP
    return Failure.BROKEN


class _TLSReusingSession(ftplib.FTP_TLS):
    """FTPS whose data connections resume the control TLS session.

    Servers such as vsftpd refuse data connections that do not. Data
    connections are always protected (``PROT P`` is sent at login).
    """

    def ntransfercmd(
        self, cmd: str, rest: int | str | None = None
    ) -> tuple[socket.socket, int | None]:
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        wrapped = self.context.wrap_socket(
            conn,
            server_hostname=self.host,
            session=self.sock.session,  # type: ignore[union-attr]
        )
        return wrapped, size


@dataclass(slots=True)
class FtpConnection:
    """Logged-in FTP session.

    Attributes:
        ftp: ``ftplib`` client in binary mode.
        features: Upper-cased ``FEAT`` keywords (``MLST``, ``MDTM``...).
        home: Working directory after login.
    """

    ftp: ftplib.FTP
    features: frozenset[str]
    home: str


class FtpStorageAdapter:
    """Storage adapter for a directory on an FTP server.

    Uses ``MLST``/``MLSD`` when the server has them and ``SIZE``,
    ``MDTM`` and ``LIST`` otherwise. Writes go to a temporary file that
    is renamed over the target. The server's passive-mode address is
    ignored: data connections go to the configured host.

    Args:
        options: FTP settings.
    """

    def __init__(self, options: FtpOptions) -> None:
        self.options = options
        self._transfers = TransferThreads()
        self._pool = ConnectionPool(
            self._connect,
            _close,
            lambda error, _: classify(error),
            size=options.connections,
            idle_timeout=options.idle_timeout,
        )

    def close(self) -> None:
        """Close the idle connections."""
        self._pool.close()

    def _remote(self, path: str) -> str:
        return remote_path(self.options.directory, path)

    def _connect(self) -> FtpConnection:
        options = self.options
        ftp: ftplib.FTP
        if options.tls:
            context = ssl.create_default_context()
            if not options.verify_certificate:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            ftp = _TLSReusingSession(
                context=context,
                timeout=options.timeout,
                encoding=options.encoding,
            )
        else:
            ftp = ftplib.FTP(
                timeout=options.timeout, encoding=options.encoding
            )
        try:
            ftp.connect(options.host, options.port)
            ftp.login(options.username, options.password)
            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.prot_p()
            features = _features(ftp)
            if "UTF8" in features:
                with contextlib.suppress(ftplib.Error):
                    ftp.voidcmd("OPTS UTF8 ON")
            ftp.voidcmd("TYPE I")
            home = ftp.pwd()
        except BaseException:
            ftp.close()
            raise
        return FtpConnection(ftp, features, home)

    # --- blocking helpers, run with a pooled connection ------------------

    def _stat(self, conn: FtpConnection, path: str) -> StatEntry:
        if not path:
            return StatEntry("", is_file=False, last_modified_ms=0)
        return self._stat_at(conn, self._remote(path), path)

    def _stat_at(
        self, conn: FtpConnection, remote: str, path: str
    ) -> StatEntry:
        if "MLST" in conn.features:
            try:
                answer = conn.ftp.sendcmd(f"MLST {remote}")
            except ftplib.Error as error:
                if _is_missing(error):
                    raise FileNotFoundError(path) from None
                raise
            lines = [line for line in answer.splitlines() if line[:1] == " "]
            if not lines:
                msg = f"Unexpected MLST answer for {path}"
                raise ftplib.error_reply(msg)
            entry = parse_facts(lines[0].strip())
            return self._stat_entry(path, entry)
        return self._stat_without_mlst(conn, path, remote)

    @staticmethod
    def _stat_entry(path: str, entry: ListedEntry) -> StatEntry:
        if entry.kind == "file":
            return StatEntry(
                path,
                is_file=True,
                size=entry.size or 0,
                last_modified_ms=entry.last_modified_ms or 0,
            )
        if entry.kind == "dir":
            return StatEntry(
                path,
                is_file=False,
                last_modified_ms=entry.last_modified_ms or 0,
            )
        raise UnsupportedEntryError

    def _stat_without_mlst(
        self, conn: FtpConnection, path: str, remote: str
    ) -> StatEntry:
        try:
            size = conn.ftp.size(remote)
        except ftplib.error_perm:
            size = None
        if size is not None:
            modified = 0.0
            if "MDTM" in conn.features:
                try:
                    answer = conn.ftp.sendcmd(f"MDTM {remote}")
                except ftplib.error_perm:
                    pass
                else:
                    modified = parse_time(answer[4:]) or 0.0
            return StatEntry(
                path, is_file=True, size=size, last_modified_ms=modified
            )
        if self._enters(conn, remote):
            return StatEntry(path, is_file=False, last_modified_ms=0)
        raise FileNotFoundError(path)

    @staticmethod
    def _enters(conn: FtpConnection, remote: str) -> bool:
        try:
            conn.ftp.cwd(remote)
        except ftplib.error_perm:
            return False
        conn.ftp.cwd(conn.home)
        return True

    def _exists(self, conn: FtpConnection, path: str) -> StatEntry | None:
        try:
            return self._stat(conn, path)
        except FileNotFoundError:
            return None

    def _entries(
        self, conn: FtpConnection, path: str
    ) -> builtins.list[ListedEntry]:
        remote = self._remote(path)
        try:
            if "MLST" in conn.features:
                return parse_mlsd(
                    conn.ftp.mlsd(remote, facts=["type", "size", "modify"])
                )
            lines: builtins.list[str] = []
            conn.ftp.retrlines(f"LIST {remote}", lines.append)
        except ftplib.Error as error:
            if _is_missing(error):
                raise FileNotFoundError(path) from None
            raise
        return parse_listing(lines)

    def _scan(
        self, conn: FtpConnection, path: str, deep: bool
    ) -> builtins.list[StatEntry]:
        result: builtins.list[StatEntry] = []
        pending = [path]
        while pending:
            current = pending.pop(0)
            for entry in self._entries(conn, current):
                relative = f"{current}/{entry.name}" if current else entry.name
                if entry.kind == "file":
                    result.append(
                        StatEntry(
                            relative,
                            is_file=True,
                            size=entry.size,
                            last_modified_ms=entry.last_modified_ms,
                        )
                    )
                elif entry.kind == "dir":
                    result.append(
                        StatEntry(
                            relative,
                            is_file=False,
                            last_modified_ms=entry.last_modified_ms or 0,
                        )
                    )
                    if deep:
                        pending.append(relative)
                else:
                    logger.warning(
                        "Skipping %s: not a regular file or directory",
                        relative,
                    )
        return result

    def _make_directories(self, conn: FtpConnection, path: str) -> None:
        if not path:
            return
        try:
            conn.ftp.mkd(self._remote(path))
        except ftplib.error_perm:
            parts = path.split("/")
            for index in range(1, len(parts) + 1):
                with contextlib.suppress(ftplib.error_perm):
                    conn.ftp.mkd(self._remote("/".join(parts[:index])))
            entry = self._exists(conn, path)
            if entry is None or entry.is_file:
                raise

    def _make_parents(self, conn: FtpConnection, path: str) -> None:
        parent = path.rpartition("/")[0]
        self._make_directories(conn, parent)

    def _is_file_at(self, conn: FtpConnection, remote: str) -> bool:
        try:
            return self._stat_at(conn, remote, remote).is_file
        except FileNotFoundError, UnsupportedEntryError:
            return False

    def _replace(self, conn: FtpConnection, source: str, target: str) -> None:
        """Rename an existing file ``source`` to ``target``.

        A server refusing to rename over a file gets the file moved aside
        first and put back if the rename still fails, so it is never
        lost; any other target (a directory) fails the rename.
        """
        try:
            conn.ftp.rename(source, target)
        except ftplib.error_perm:
            if not self._is_file_at(conn, target):
                raise
            replace_by_swap(conn.ftp.rename, conn.ftp.delete, source, target)

    def _store(
        self, conn: FtpConnection, path: str, file: BinaryIO, start: int
    ) -> None:
        remote = self._remote(path)
        directory, _, _ = remote.rpartition("/")
        temporary = f".{uuid.uuid4().hex}.tmp"
        if directory or remote.startswith("/"):
            temporary = f"{directory}/{temporary}"

        def upload() -> None:
            file.seek(start)
            _send(conn, f"STOR {temporary}", file)

        try:
            try:
                upload()
            except ftplib.error_perm:
                self._make_parents(conn, path)
                upload()
            self._replace(conn, temporary, remote)
        except BaseException:
            with contextlib.suppress(Exception):
                conn.ftp.delete(temporary)
            raise

    def _retrieve(
        self, conn: FtpConnection, path: str, sink: BinaryIO
    ) -> None:
        try:
            conn.ftp.retrbinary(
                f"RETR {self._remote(path)}", sink.write, CHUNK_SIZE
            )
        except ftplib.error_perm as error:
            if _is_missing(error):
                raise FileWasNotFoundError(path) from None
            raise

    def _read(self, conn: FtpConnection, path: str) -> bytes:
        sink = BytesIO()
        self._retrieve(conn, path, sink)
        return sink.getvalue()

    def _copy(
        self, conn: FtpConnection, source: str, destination: str
    ) -> None:
        with tempfile.SpooledTemporaryFile(max_size=SPOOL_SIZE) as spool:
            buffer: BinaryIO = spool  # type: ignore[assignment]
            self._retrieve(conn, source, buffer)
            self._store(conn, destination, buffer, 0)

    def _delete_file(self, conn: FtpConnection, path: str) -> None:
        try:
            conn.ftp.delete(self._remote(path))
        except ftplib.error_perm:
            if self._exists(conn, path) is None:
                return
            raise

    def _delete_directory(self, conn: FtpConnection, path: str) -> None:
        entry = self._exists(conn, path)
        if entry is None:
            return
        if entry.is_file:
            conn.ftp.delete(self._remote(path))
            return
        entries = self._scan(conn, path, deep=True)
        for item in entries:
            if item.is_file:
                conn.ftp.delete(self._remote(item.path))
        folders = sorted(
            (item.path for item in entries if item.is_directory),
            key=lambda folder: folder.count("/"),
            reverse=True,
        )
        for folder in folders:
            conn.ftp.rmd(self._remote(folder))
        if path:
            conn.ftp.rmd(self._remote(path))

    def _move(
        self, conn: FtpConnection, source: str, destination: str
    ) -> None:
        origin = self._stat(conn, source)
        self._make_parents(conn, destination)
        remote, target = self._remote(source), self._remote(destination)
        if origin.is_file:
            self._replace(conn, remote, target)
        else:
            conn.ftp.rename(remote, target)

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

        Args:
            path: File path.

        Yields:
            Chunks of at most ``CHUNK_SIZE`` bytes.

        Raises:
            FileWasNotFoundError: The file does not exist.
        """
        remote = self._remote(path)
        async with self._pool.hold(_noop) as conn:
            try:
                data = await self._transfers.run(
                    conn.ftp.transfercmd, f"RETR {remote}"
                )
            except ftplib.error_perm as error:
                if _is_missing(error):
                    raise FileWasNotFoundError(path) from None
                raise
            try:
                while chunk := await self._transfers.run(
                    data.recv, CHUNK_SIZE
                ):
                    yield chunk
            finally:
                await self._transfers.run(data.close)
            await self._transfers.run(conn.ftp.voidresp)

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
        """Read metadata of a file or directory.

        Args:
            path: Entry path.

        Returns:
            Metadata; directories have no time without ``MLST``.

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
            Entries in server order, with size and time when the listing
            has them; links and other entries are skipped.
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
        """Copy a file through the connector (FTP has no server copy).

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


def _features(ftp: ftplib.FTP) -> frozenset[str]:
    try:
        answer = ftp.sendcmd("FEAT")
    except ftplib.Error:
        return frozenset()
    return frozenset(
        line.strip().split(" ", 1)[0].upper()
        for line in answer.splitlines()[1:-1]
        if line.strip()
    )


def _send(conn: FtpConnection, command: str, file: BinaryIO) -> None:
    """Upload ``file`` with ``command`` (``STOR``).

    When reading ``file`` or sending fails, the transfer is closed and
    its reply consumed, so the connection can still clean up.
    """
    data = conn.ftp.transfercmd(command)
    try:
        with data:
            while chunk := file.read(CHUNK_SIZE):
                data.sendall(chunk)
            if isinstance(data, ssl.SSLSocket):
                data.unwrap()
    except BaseException:
        with contextlib.suppress(Exception):
            conn.ftp.getresp()
        raise
    conn.ftp.voidresp()


def _noop(conn: FtpConnection) -> None:
    conn.ftp.voidcmd("NOOP")


def _close(conn: FtpConnection) -> None:
    conn.ftp.close()
