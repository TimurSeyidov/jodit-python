"""Path-normalizing, error-wrapping facade over a storage adapter."""

import os
import posixpath
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from jcpy.storage.base import StorageError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from jcpy.storage.base import StatEntry, StorageAdapter


class PathTraversalError(StorageError):
    """Path escapes the storage root."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"Path traversal detected for: {path}",
            "flystorage.path_traversal_detected",
        )


class CorruptedPathError(StorageError):
    """Path contains control or other invisible characters."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"Corrupted path detected with unexpected whitespace: {path}",
            "flystorage.corrupted_path_detected",
        )


def normalize_storage_path(path: str) -> str:
    """Normalize a storage path like flystorage's ``PathNormalizerV1``.

    Args:
        path: Path relative to the storage root; a leading ``/`` is
            ignored.

    Returns:
        Normalized path; ``""`` for the root.

    Raises:
        CorruptedPathError: The path contains a Unicode ``C``
            category character (control, format, unassigned ...).
        PathTraversalError: The path resolves above the root.
    """
    if any(unicodedata.category(char).startswith("C") for char in path):
        raise CorruptedPathError(path)
    segments = [segment for segment in path.split("/") if segment]
    normalized = posixpath.normpath("/".join(segments)) if segments else "."
    if "../" in normalized or normalized == "..":
        raise PathTraversalError(path)
    return "" if normalized == "." else normalized


def _root_spellings(adapter: object) -> list[str]:
    root = getattr(adapter, "root", None)
    if not isinstance(root, Path):
        return []
    spellings = {str(root), os.path.realpath(root), str(root.absolute())}
    # Longest first, so that no shorter spelling leaves a remainder.
    return sorted(spellings, key=len, reverse=True)


class FileStorage:
    """Storage used by sources: normalizes paths, wraps failures.

    Every failure is re-raised as ``StorageError`` whose message starts
    with the failed operation (``Unable to get stat. Reason: ...``).

    Args:
        adapter: Backend implementation.
    """

    def __init__(self, adapter: StorageAdapter) -> None:
        self.adapter = adapter
        self._roots = _root_spellings(adapter)

    def _reason(self, error: Exception) -> str:
        """Describe an adapter failure without the storage location.

        Operating system errors name absolute paths; they are shown
        relative to the storage root so that answers do not reveal the
        server's directory layout.
        """
        reason = str(error) or type(error).__name__
        for root in self._roots:
            reason = reason.replace(f"{root}/", "").replace(root, ".")
        return reason

    async def write(self, path: str, contents: bytes) -> None:
        """Create or replace a file.

        Args:
            path: File path.
            contents: File contents.

        Raises:
            StorageError: The file cannot be written.
        """
        try:
            await self.adapter.write(normalize_storage_path(path), contents)
        except Exception as error:
            msg = f"Unable to write the file. Reason: {self._reason(error)}"
            raise StorageError(
                msg, "flystorage.unable_to_write_file"
            ) from error

    async def read(self, path: str) -> bytes:
        """Read a whole file.

        Args:
            path: File path.

        Returns:
            File contents.

        Raises:
            StorageError: The file cannot be read.
        """
        try:
            return await self.adapter.read(normalize_storage_path(path))
        except Exception as error:
            msg = f"Unable to read the file. Reason: {self._reason(error)}"
            raise StorageError(
                msg, "flystorage.unable_to_read_file"
            ) from error

    async def delete_file(self, path: str) -> None:
        """Delete a file.

        Args:
            path: File path.

        Raises:
            StorageError: The file cannot be deleted.
        """
        try:
            await self.adapter.delete_file(normalize_storage_path(path))
        except Exception as error:
            msg = f"Unable to delete file. Reason: {self._reason(error)}"
            raise StorageError(
                msg, "flystorage.unable_to_delete_file"
            ) from error

    async def create_directory(self, path: str) -> None:
        """Create a directory with its missing parents.

        Args:
            path: Directory path.

        Raises:
            StorageError: The directory cannot be created.
        """
        try:
            await self.adapter.create_directory(normalize_storage_path(path))
        except Exception as error:
            msg = f"Unable to create directory. Reason: {self._reason(error)}"
            raise StorageError(
                msg, "flystorage.unable_to_create_directory"
            ) from error

    async def delete_directory(self, path: str) -> None:
        """Delete a directory recursively.

        Args:
            path: Directory path.

        Raises:
            StorageError: The directory cannot be deleted.
        """
        try:
            await self.adapter.delete_directory(normalize_storage_path(path))
        except Exception as error:
            msg = f"Unable to delete directory. Reason: {self._reason(error)}"
            raise StorageError(
                msg, "flystorage.unable_to_delete_directory"
            ) from error

    async def stat(self, path: str) -> StatEntry:
        """Read metadata of a file or directory.

        Args:
            path: Entry path.

        Returns:
            Metadata.

        Raises:
            StorageError: The entry cannot be inspected.
        """
        try:
            return await self.adapter.stat(normalize_storage_path(path))
        except Exception as error:
            msg = f"Unable to get stat. Reason: {self._reason(error)}"
            raise StorageError(msg, "flystorage.unable_to_get_stat") from error

    async def list(
        self, path: str, *, deep: bool = False
    ) -> AsyncIterator[StatEntry]:
        """List a directory.

        Args:
            path: Directory path.
            deep: Include nested entries.

        Yields:
            Entries in storage order.

        Raises:
            StorageError: The directory cannot be listed.
        """
        normalized = normalize_storage_path(path)
        try:
            async for entry in self.adapter.list(normalized, deep=deep):
                yield entry
        except Exception as error:
            reason = self._reason(error)
            msg = f"Unable to list directory contents. Reason: {reason}"
            raise StorageError(
                msg, "flystorage.unable_to_list_directory"
            ) from error

    async def file_exists(self, path: str) -> bool:
        """Tell whether a file exists.

        Args:
            path: File path.

        Returns:
            ``True`` for an existing file.

        Raises:
            StorageError: Existence cannot be checked.
        """
        try:
            return await self.adapter.file_exists(normalize_storage_path(path))
        except Exception as error:
            reason = self._reason(error)
            msg = f"Unable to check file existence. Reason: {reason}"
            raise StorageError(
                msg, "flystorage.unable_to_check_file_existence"
            ) from error

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a directory exists.

        Args:
            path: Directory path.

        Returns:
            ``True`` for an existing directory.

        Raises:
            StorageError: Existence cannot be checked.
        """
        try:
            return await self.adapter.directory_exists(
                normalize_storage_path(path)
            )
        except Exception as error:
            msg = (
                "Unable to check directory existence. "
                f"Reason: {self._reason(error)}"
            )
            raise StorageError(
                msg, "flystorage.unable_to_check_directory_existence"
            ) from error

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy a file.

        Args:
            source: Existing file path.
            destination: New file path.

        Raises:
            StorageError: The file cannot be copied.
        """
        try:
            await self.adapter.copy_file(
                normalize_storage_path(source),
                normalize_storage_path(destination),
            )
        except Exception as error:
            msg = f"Unable to copy file. Reason: {self._reason(error)}"
            raise StorageError(
                msg, "flystorage.unable_to_copy_file"
            ) from error

    async def move_file(self, source: str, destination: str) -> None:
        """Move a file or directory.

        Args:
            source: Existing path.
            destination: New path.

        Raises:
            StorageError: The entry cannot be moved.
        """
        try:
            await self.adapter.move_file(
                normalize_storage_path(source),
                normalize_storage_path(destination),
            )
        except Exception as error:
            msg = f"Unable to move file. Reason: {self._reason(error)}"
            raise StorageError(
                msg, "flystorage.unable_to_move_file"
            ) from error
