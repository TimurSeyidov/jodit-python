"""File download: ``action=fileDownload``."""

from typing import TYPE_CHECKING
from urllib.parse import quote

from starlette.responses import Response

from jcpy.errors import HttpError
from jcpy.services.download import read_file
from jcpy.sources import SOURCE_NOT_FOUND
from jcpy.validation import Issue, require_valid, string_field

if TYPE_CHECKING:
    from jcpy.context import ActionContext
    from jcpy.types import JsonObject


def content_disposition(name: str) -> str:
    """Build the attachment header for a file name.

    Args:
        name: File name as requested.

    Returns:
        ``attachment; filename="name"``; names outside Latin-1 get an
        ASCII fallback plus an RFC 5987 ``filename*``.
    """
    try:
        name.encode("latin-1")
    except UnicodeEncodeError:
        fallback = name.encode("ascii", "replace").decode().replace("?", "_")
        return (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(name)}"
        )
    return f'attachment; filename="{name}"'


def validate(data: JsonObject) -> list[Issue]:
    """Check ``fileDownload`` parameters.

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    return [
        *string_field(data, "source", required=False),
        *string_field(data, "path", required=False),
        *string_field(data, "name", required=True),
    ]


async def file_download_handler(context: ActionContext) -> Response:
    """Send a file of the first selected source as an attachment.

    Args:
        context: Action context.

    Returns:
        ``application/octet-stream`` response with the file contents.

    Raises:
        HttpError: ``400`` for invalid parameters or a directory,
            ``403`` without ``FILE_DOWNLOAD`` permission, ``404`` for
            an unknown source, a missing file or a name leaving the
            directory.
    """
    params = context.params
    require_valid(validate(params.data))
    sources = await context.get_sources()
    if not sources:
        raise HttpError.not_found(SOURCE_NOT_FOUND)
    name = params.get_str("name", "")
    if not name:
        raise HttpError.bad_request("Name parameter is required")

    contents = await read_file(context, sources[0], name, params.path)
    return Response(
        contents,
        media_type="application/octet-stream",
        headers={
            "Content-Description": "File Transfer",
            "Content-Disposition": content_disposition(name),
            "Content-Transfer-Encoding": "binary",
        },
    )
