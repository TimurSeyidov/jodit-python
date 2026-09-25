"""File uploads."""

import os
import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING

from anyio import to_thread

from jcpy.errors import HttpError
from jcpy.helpers.js import node_basename, parse_bytes, sanitize_filename

if TYPE_CHECKING:
    from starlette.datastructures import UploadFile

    from jcpy.context import ActionContext
    from jcpy.sources import Source


@dataclass(frozen=True, slots=True)
class StoredFile:
    """File written by an upload.

    Attributes:
        path: Storage path relative to the source root.
        name: File name.
        is_image: Whether the extension is an image one.
    """

    path: str
    name: str
    is_image: bool


async def _free_name(source: Source, directory: str, file_name: str) -> str:
    """Apply ``saveSameFileNameStrategy`` to a taken name.

    Returns:
        Absolute target path.
    """
    target = posixpath.join(directory, file_name)
    if not await source.storage.file_exists(source.storage_path(target)):
        return target
    strategy = source.config.save_same_file_name_strategy or "addNumber"
    if strategy == "error":
        msg = f"File {file_name} already exists"
        raise HttpError.bad_request(msg)
    if strategy == "replace":
        return target
    extension = source.get_extension(file_name)
    stem = node_basename(file_name, f".{extension}")
    counter = 1
    while True:
        target = posixpath.join(directory, f"{stem}-{counter}.{extension}")
        counter += 1
        if not await source.storage.file_exists(source.storage_path(target)):
            return target


async def _upload_size(upload: UploadFile) -> int:
    """Size of an uploaded file, measured when the parser left it unset."""
    if upload.size is not None:
        return upload.size

    def measure() -> int:
        upload.file.seek(0, os.SEEK_END)
        size = upload.file.tell()
        upload.file.seek(0)
        return size

    return await to_thread.run_sync(measure)


def _check_upload(source: Source, storage_path: str, size: int) -> None:
    if not source.is_safe_file(storage_path):
        raise HttpError.forbidden("File type is not in white list")
    limit = source.config.max_upload_file_size
    if limit and size > (parse_bytes(limit) or 0):
        raise HttpError.forbidden("File size exceeds the allowable")


async def upload_files(
    context: ActionContext,
    source: Source,
    files: list[UploadFile],
    relative_path: str,
) -> list[StoredFile]:
    """Store uploaded files in a directory of a source.

    Names are sanitized (unsafe characters become ``_``); a taken name
    follows ``saveSameFileNameStrategy``: ``addNumber`` (``a-1.txt``),
    ``replace`` or ``error``. Each stored file must have an allowed
    extension, fit ``maxUploadFileSize`` and pass ``FILE_UPLOAD`` for
    its extension. Every file is checked before any is written, so a
    rejected request changes nothing.

    Args:
        context: Action context (role and access control).
        source: Source to store into.
        files: Uploaded files.
        relative_path: Target directory relative to the source root.

    Returns:
        Stored files in upload order.

    Raises:
        HttpError: ``400`` for a taken name with the ``error``
            strategy, ``403`` for a forbidden extension, size or
            permission.
    """
    directory = await source.get_path(relative_path)
    # Check every file before writing any: a rejected upload must never
    # overwrite (and then remove) an existing file of the same name.
    pending: list[tuple[str, UploadFile]] = []
    for upload in files:
        file_name = sanitize_filename(upload.filename or "", "_")
        target = await _free_name(source, directory, file_name)
        storage_path = source.storage_path(target)
        _check_upload(source, storage_path, await _upload_size(upload))
        await context.access.check_permission(
            context.role,
            "FILE_UPLOAD",
            source.get_root(),
            source.get_extension(storage_path),
        )
        pending.append((storage_path, upload))

    stored: list[StoredFile] = []
    for storage_path, upload in pending:
        # Streamed from the upload's temporary file, not read into memory.
        await upload.seek(0)
        await source.storage.write_file(storage_path, upload.file)
        stat = await source.storage.stat(storage_path)
        stored.append(
            StoredFile(
                stat.path,
                posixpath.basename(storage_path),
                source.is_image(storage_path),
            )
        )
    return stored
