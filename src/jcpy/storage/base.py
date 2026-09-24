"""Storage adapter interface and shared types."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class StatEntry:
    """File or directory metadata.

    Attributes:
        path: Path relative to the storage root, without a trailing
            slash.
        is_file: ``True`` for files, ``False`` for directories.
        size: Size in bytes; unknown for directories and listings.
        last_modified_ms: Modification time in epoch milliseconds;
            unknown for listings.
    """

    path: str
    is_file: bool
    size: int | None = None
    last_modified_ms: float | None = None

    @property
    def is_directory(self) -> bool:
        """Whether the entry is a directory."""
        return not self.is_file

    @property
    def type(self) -> Literal["file", "directory"]:
        """Entry type as reported to clients."""
        return "file" if self.is_file else "directory"


class StorageError(Exception):
    """Storage operation failed.

    Args:
        message: Human readable description.
        code: Machine readable error kind.
    """

    def __init__(self, message: str, code: str = "unknown_error") -> None:
        super().__init__(message)
        self.code = code


class FileWasNotFoundError(StorageError):
    """Read of a missing file."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"File was not found at location: {path}",
            "storage.file_was_not_found",
        )


class StorageAdapter(Protocol):
    """Low-level access to one storage backend.

    Paths are normalized, relative to the adapter root and use ``/``;
    the empty string is the root itself.
    """

    async def write(self, path: str, contents: bytes) -> None:
        """Create or replace a file, creating parent directories.

        Args:
            path: File path.
            contents: File contents.
        """
        ...

    async def read(self, path: str) -> bytes:
        """Read a whole file.

        Args:
            path: File path.

        Returns:
            File contents.

        Raises:
            FileWasNotFoundError: The file does not exist.
        """
        ...

    async def delete_file(self, path: str) -> None:
        """Delete a file; a missing file is not an error.

        Args:
            path: File path.
        """
        ...

    async def create_directory(self, path: str) -> None:
        """Create a directory with its missing parents.

        Args:
            path: Directory path.
        """
        ...

    async def delete_directory(self, path: str) -> None:
        """Delete a directory recursively; missing is not an error.

        Args:
            path: Directory path.
        """
        ...

    async def stat(self, path: str) -> StatEntry:
        """Read metadata of a file or directory.

        Args:
            path: Entry path.

        Returns:
            Metadata with size and modification time.
        """
        ...

    def list(self, path: str, *, deep: bool) -> AsyncIterator[StatEntry]:
        """List a directory.

        Args:
            path: Directory path.
            deep: Include nested entries.

        Returns:
            Entries in storage order; size and time may be unknown.
        """
        ...

    async def file_exists(self, path: str) -> bool:
        """Tell whether a file exists.

        Args:
            path: File path.

        Returns:
            ``True`` for an existing file (not a directory).
        """
        ...

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a directory exists.

        Args:
            path: Directory path.

        Returns:
            ``True`` for an existing directory.
        """
        ...

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy a file, creating parent directories of the destination.

        Args:
            source: Existing file path.
            destination: New file path.
        """
        ...

    async def move_file(self, source: str, destination: str) -> None:
        """Move a file or directory, creating destination parents.

        Args:
            source: Existing path.
            destination: New path.
        """
        ...
