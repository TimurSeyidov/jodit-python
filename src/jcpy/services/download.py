"""File download."""

import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.sources import PATH_NOT_FOUND, is_path_within_root

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from jcpy.context import ActionContext
    from jcpy.sources import Source


@dataclass(frozen=True, slots=True)
class Download:
    """File contents ready to stream.

    Attributes:
        size: Size in bytes, when the storage reports it.
        chunks: Contents in chunks; the first one is already read, so
            a missing file fails before the response starts.
    """

    size: int | None
    chunks: AsyncIterator[bytes]


async def _prepend(
    first: bytes, rest: AsyncIterator[bytes]
) -> AsyncIterator[bytes]:
    yield first
    async for chunk in rest:
        yield chunk


async def open_download(
    context: ActionContext, source: Source, name: str, relative_path: str
) -> Download:
    """Open a file for download without reading it into memory.

    Args:
        context: Action context (role and access control).
        source: Source holding the file.
        name: File name inside the directory.
        relative_path: Directory relative to the source root.

    Returns:
        Size and chunks of the file.

    Raises:
        HttpError: ``403`` without ``FILE_DOWNLOAD`` permission,
            ``404`` when the name leaves the directory or the file is
            missing, ``400 It is not a file!`` for directories.
    """
    directory = await source.get_path(relative_path)
    await context.access.check_permission(
        context.role, "FILE_DOWNLOAD", directory
    )
    target = await source.validate_path(posixpath.join(directory, name))
    if not is_path_within_root(target, directory):
        raise HttpError.not_found(PATH_NOT_FOUND)

    storage_path = source.relative(target)
    try:
        stat = await source.storage.stat(storage_path)
        if not stat.is_file:
            raise HttpError.bad_request("It is not a file!")
        chunks = source.storage.iter_file(storage_path)
        first = await anext(chunks, b"")
    except HttpError:
        raise
    except Exception:
        raise HttpError.not_found("File or directory not exists") from None
    return Download(stat.size, _prepend(first, chunks))
