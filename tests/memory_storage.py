"""In-memory storage adapter for tests."""

from typing import TYPE_CHECKING

from jcpy.storage.base import FileWasNotFoundError, StatEntry

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator


class MemoryStorageAdapter:
    """Keep files in a dict; directories are implied or explicit."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.directories: set[str] = {""}

    def _add_parents(self, path: str) -> None:
        parts = path.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            self.directories.add("/".join(parts[:index]))

    async def write(self, path: str, contents: bytes) -> None:
        """Store a file."""
        self._add_parents(path)
        self.files[path] = contents

    async def read(self, path: str) -> bytes:
        """Return a stored file."""
        if path not in self.files:
            raise FileWasNotFoundError(path)
        return self.files[path]

    async def delete_file(self, path: str) -> None:
        """Forget a file."""
        self.files.pop(path, None)

    async def create_directory(self, path: str) -> None:
        """Remember a directory and its parents."""
        self._add_parents(f"{path}/")
        self.directories.add(path)

    async def delete_directory(self, path: str) -> None:
        """Forget a directory tree."""
        prefix = f"{path}/"
        self.files = {
            key: value
            for key, value in self.files.items()
            if not key.startswith(prefix)
        }
        self.directories = {
            item
            for item in self.directories
            if item != path and not item.startswith(prefix)
        }

    async def stat(self, path: str) -> StatEntry:
        """Describe a file or directory."""
        if path in self.files:
            return StatEntry(path, True, len(self.files[path]), 0.0)
        if path in self.directories:
            return StatEntry(path, False, None, 0.0)
        msg = f"Path not found: {path}"
        raise FileNotFoundError(msg)

    async def list(self, path: str, *, deep: bool) -> AsyncIterator[StatEntry]:
        """List stored entries below a directory."""
        prefix = f"{path}/" if path else ""
        entries: builtins.list[StatEntry] = [
            StatEntry(item, is_file=False)
            for item in sorted(self.directories)
            if item and item.startswith(prefix)
        ] + [
            StatEntry(item, is_file=True)
            for item in sorted(self.files)
            if item.startswith(prefix)
        ]
        for entry in entries:
            if deep or "/" not in entry.path[len(prefix) :]:
                yield entry

    async def file_exists(self, path: str) -> bool:
        """Tell whether a file is stored."""
        return path in self.files

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a directory is known."""
        return path in self.directories

    async def copy_file(self, source: str, destination: str) -> None:
        """Duplicate a file."""
        await self.write(destination, await self.read(source))

    async def move_file(self, source: str, destination: str) -> None:
        """Rename a file."""
        await self.write(destination, self.files.pop(source))
