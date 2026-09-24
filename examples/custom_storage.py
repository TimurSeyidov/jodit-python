"""Custom storage adapter, registered by name.

Files live in process memory, so they vanish on restart; the adapter
shows the interface a real backend (a database, another object store)
implements. Sources select it with ``"storageAdapter": "memory"``.

Run from the repository root::

    uv run python examples/custom_storage.py
    curl -F "files[0]=@README.md" "http://localhost:8081/fileUpload"
    curl "http://localhost:8081/files"
"""

import time
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from jcpy import create_app, register_storage_adapter
from jcpy.storage.base import FileWasNotFoundError, StatEntry, StorageError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from jcpy import SourceConfig

CONFIG = Path(__file__).parent / "config" / "memory.json"


# --8<-- [start:build]
class MemoryStorageAdapter:
    """Keep files in a dict; paths are relative and use ``/``."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, float]] = {}
        self.directories: set[str] = {""}

    def _add_parents(self, path: str) -> None:
        parts = path.split("/")
        for index in range(1, len(parts)):
            self.directories.add("/".join(parts[:index]))

    async def write(self, path: str, contents: bytes) -> None:
        """Create or replace a file."""
        self._add_parents(path)
        self.files[path] = (contents, time.time() * 1000)

    async def read(self, path: str) -> bytes:
        """Read a whole file."""
        if path not in self.files:
            raise FileWasNotFoundError(path)
        return self.files[path][0]

    async def delete_file(self, path: str) -> None:
        """Delete a file; a missing file is not an error."""
        self.files.pop(path, None)

    async def create_directory(self, path: str) -> None:
        """Create a directory with its parents."""
        self._add_parents(path)
        self.directories.add(path)

    async def delete_directory(self, path: str) -> None:
        """Delete a directory recursively."""
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
        """Read size and modification time."""
        if path in self.files:
            contents, modified = self.files[path]
            return StatEntry(path, True, len(contents), modified)
        if path in self.directories:
            return StatEntry(path, False)
        msg = f"Unable to get stat. Reason: {path} does not exist"
        raise StorageError(msg)

    async def list(self, path: str, *, deep: bool) -> AsyncIterator[StatEntry]:
        """List a directory (and its sub-directories when ``deep``)."""
        prefix = f"{path}/" if path else ""
        entries = [
            StatEntry(item, is_file=False)
            for item in sorted(self.directories)
            if item and item.startswith(prefix)
        ] + [
            StatEntry(item, is_file=True)
            for item in sorted(self.files)
            if item.startswith(prefix)
        ]
        for entry in entries:
            if deep or "/" not in entry.path.removeprefix(prefix):
                yield entry

    async def file_exists(self, path: str) -> bool:
        """Tell whether a file exists."""
        return path in self.files

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a directory exists."""
        return path in self.directories

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy a file."""
        await self.write(destination, await self.read(source))

    async def move_file(self, source: str, destination: str) -> None:
        """Move a file or a whole directory."""
        if source in self.files:
            self._add_parents(destination)
            self.files[destination] = self.files.pop(source)
            return
        prefix = f"{source}/"
        for key in [key for key in self.files if key.startswith(prefix)]:
            await self.write(
                f"{destination}/{key.removeprefix(prefix)}",
                self.files.pop(key)[0],
            )
        for item in sorted(self.directories):
            if item == source or item.startswith(prefix):
                self.directories.discard(item)
                await self.create_directory(
                    destination + item.removeprefix(source)
                )


_STORES: dict[str, MemoryStorageAdapter] = {}


def memory_adapter(source: SourceConfig) -> MemoryStorageAdapter:
    """Give every source its own store, kept between requests.

    Args:
        source: Settings of the source using the adapter.

    Returns:
        Store of the source.
    """
    return _STORES.setdefault(source.name, MemoryStorageAdapter())


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Connector application with in-memory sources.
    """
    register_storage_adapter("memory", memory_adapter)
    return create_app(CONFIG)


# --8<-- [end:build]

if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
