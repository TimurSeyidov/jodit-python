"""File upload: ``action=fileUpload``."""

from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.responses import success_response
from jcpy.services.upload import upload_files
from jcpy.v1.common import first_source, string_fields
from jcpy.validation import require_valid_plain

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.types import JsonValue


async def file_upload_handler(context: ActionContext) -> Response:
    """Store the files of a multipart request.

    Files are taken from the field named by ``defaultFilesKey`` (of the
    source, else global) and from ``files[...]`` fields.

    Args:
        context: Action context.

    Returns:
        ``{"baseurl", "messages", "files", "isImages"}`` where ``files``
        are paths relative to the source root.

    Raises:
        HttpError: ``400`` for invalid parameters or no files, ``403``
            for denied uploads, ``404`` for an unknown source or path.
    """
    params = context.params
    require_valid_plain(string_fields(params.data))
    source = await first_source(context)
    files_key = (
        source.settings.default_files_key or context.config.default_files_key
    )
    uploads = [
        item.file
        for item in params.files
        if item.field == files_key or item.field.startswith("files[")
    ]
    if not uploads:
        raise HttpError.bad_request("No files have been uploaded")
    await context.access.check_permission(
        context.role, params.action, await source.get_path(params.path)
    )

    stored = await upload_files(context, source, uploads, params.path)
    messages: list[JsonValue] = [
        f"File {item.name} was uploaded" for item in stored
    ]
    files: list[JsonValue] = [item.path.removeprefix("/") for item in stored]
    images: list[JsonValue] = [item.is_image for item in stored]
    return success_response(
        {
            "baseurl": source.settings.baseurl,
            "messages": messages,
            "files": files,
            "isImages": images,
        }
    )
