"""File download."""

import posixpath
from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.sources import PATH_NOT_FOUND, is_path_within_root

if TYPE_CHECKING:
    from jcpy.context import ActionContext
    from jcpy.sources import Source


async def read_file(
    context: ActionContext, source: Source, name: str, relative_path: str
) -> bytes:
    """Read a file for download.

    Args:
        context: Action context (role and access control).
        source: Source holding the file.
        name: File name inside the directory.
        relative_path: Directory relative to the source root.

    Returns:
        File contents.

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
        return await source.storage.read(storage_path)
    except HttpError:
        raise
    except Exception:
        raise HttpError.not_found("File or directory not exists") from None
