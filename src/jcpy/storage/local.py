"""Local filesystem storage adapter."""

import errno
import logging
import os
import shutil
import stat as stat_module
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from anyio import to_thread

from jcpy.storage.base import FileWasNotFoundError, StatEntry

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator, Callable

logger = logging.getLogger("jcpy")


def _replace_atomically(target: Path, fill: Callable[[Path], None]) -> None:
    """Build a file next to ``target``, then swap it in atomically.

    Readers never see a partial file and a failure leaves the previous
    file intact. The temporary file gets the usual permissions (umask),
    unlike ``mkstemp``'s 0600.
    """
    temporary = target.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        fill(temporary)
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_new(path: Path, contents: bytes) -> None:
    with path.open("xb") as file:
        file.write(contents)


class UnsupportedEntryError(OSError):
    """Entry is neither a regular file nor a directory (e.g. a symlink)."""

    def __init__(self) -> None:
        super().__init__("Unsupported file entry encountered...")


class LocalStorageAdapter:
    """Storage adapter for a directory on the local filesystem.

    Stats follow symlinks; listings skip entries that are neither files
    nor directories (symlinks, FIFOs, sockets). Writes and copies are
    atomic.

    Args:
        root_dir: Directory holding the files; created on first write.
    """

    def __init__(self, root_dir: str | Path) -> None:
        self.root = Path(root_dir)
        self._root_created = False

    def _full(self, path: str) -> Path:
        return self.root / path if path else self.root

    async def _ensure_parents(self, path: str) -> None:
        def create() -> None:
            if not self._root_created:
                self.root.mkdir(parents=True, exist_ok=True)
                self._root_created = True
            parent = Path(path).parent
            if str(parent) not in {".", "/"}:
                (self.root / parent).mkdir(parents=True, exist_ok=True)

        await to_thread.run_sync(create)

    async def write(self, path: str, contents: bytes) -> None:
        """Create or replace a file, creating parent directories.

        Args:
            path: File path.
            contents: File contents.
        """
        await self._ensure_parents(path)
        await to_thread.run_sync(
            _replace_atomically,
            self._full(path),
            lambda temporary: _write_new(temporary, contents),
        )

    async def read(self, path: str) -> bytes:
        """Read a whole file.

        Args:
            path: File path.

        Returns:
            File contents.

        Raises:
            FileWasNotFoundError: The file does not exist.
        """
        try:
            return await to_thread.run_sync(self._full(path).read_bytes)
        except FileNotFoundError:
            raise FileWasNotFoundError(path) from None

    async def delete_file(self, path: str) -> None:
        """Delete a file; a missing file is not an error.

        Args:
            path: File path.
        """
        await to_thread.run_sync(
            lambda: self._full(path).unlink(missing_ok=True)
        )

    async def create_directory(self, path: str) -> None:
        """Create a directory with its missing parents.

        Args:
            path: Directory path.
        """
        await to_thread.run_sync(
            lambda: self._full(path).mkdir(parents=True, exist_ok=True)
        )

    async def delete_directory(self, path: str) -> None:
        """Delete a directory recursively; missing is not an error.

        Args:
            path: Directory path.
        """

        def delete() -> None:
            target = self._full(path)
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)

        await to_thread.run_sync(delete)

    @staticmethod
    def _entry(info: os.stat_result, path: str) -> StatEntry:
        if stat_module.S_ISREG(info.st_mode):
            return StatEntry(
                path=path,
                is_file=True,
                size=info.st_size,
                last_modified_ms=info.st_mtime_ns / 1_000_000,
            )
        if stat_module.S_ISDIR(info.st_mode):
            return StatEntry(
                path=path,
                is_file=False,
                last_modified_ms=info.st_mtime_ns / 1_000_000,
            )
        raise UnsupportedEntryError

    async def stat(self, path: str) -> StatEntry:
        """Read metadata of a file or directory (following symlinks).

        Args:
            path: Entry path.

        Returns:
            Metadata with size and modification time.

        Raises:
            OSError: The entry does not exist or is not a regular file
                or directory.
        """
        info = await to_thread.run_sync(os.stat, self._full(path))
        return self._entry(info, path)

    async def list(self, path: str, *, deep: bool) -> AsyncIterator[StatEntry]:
        """List a directory.

        Args:
            path: Directory path.
            deep: Include nested entries.

        Yields:
            Entries in filesystem order, with size and time; entries
            that are neither files nor directories are skipped.
        """
        entries = await to_thread.run_sync(self._scan, path, deep)
        for entry in entries:
            yield entry

    def _scan(self, path: str, deep: bool) -> builtins.list[StatEntry]:
        result: builtins.list[StatEntry] = []
        pending = [path]
        while pending:
            current = pending.pop(0)
            with os.scandir(self._full(current)) as iterator:
                for item in iterator:
                    relative = (
                        f"{current}/{item.name}" if current else item.name
                    )
                    if item.is_file(follow_symlinks=False) or item.is_dir(
                        follow_symlinks=False
                    ):
                        info = item.stat(follow_symlinks=False)
                        result.append(self._entry(info, relative))
                        if deep and item.is_dir(follow_symlinks=False):
                            pending.append(relative)
                    else:
                        logger.warning(
                            "Skipping %s: not a regular file or directory",
                            relative,
                        )
        return result

    async def file_exists(self, path: str) -> bool:
        """Tell whether a file exists.

        Args:
            path: File path.

        Returns:
            ``True`` for an existing file (not a directory).

        Raises:
            OSError: The check failed for another reason than a missing
                entry.
        """
        try:
            return (await self.stat(path)).is_file
        except FileNotFoundError:
            return False

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a directory exists.

        Args:
            path: Directory path.

        Returns:
            ``True`` for an existing directory.

        Raises:
            OSError: The check failed for another reason than a missing
                entry.
        """
        try:
            info = await to_thread.run_sync(os.stat, self._full(path))
        except OSError as error:
            if error.errno in {errno.ENOENT, errno.ENOTDIR}:
                return False
            raise
        return stat_module.S_ISDIR(info.st_mode)

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy a file, creating parent directories of the destination.

        Args:
            source: Existing file path.
            destination: New file path.
        """
        await self._ensure_parents(destination)
        origin = self._full(source)
        await to_thread.run_sync(
            _replace_atomically,
            self._full(destination),
            lambda temporary: shutil.copyfile(origin, temporary),
        )

    async def move_file(self, source: str, destination: str) -> None:
        """Move a file or directory, creating destination parents.

        Args:
            source: Existing path.
            destination: New path.
        """
        await self._ensure_parents(destination)
        await to_thread.run_sync(
            os.rename, self._full(source), self._full(destination)
        )
