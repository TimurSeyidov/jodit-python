"""URL to file lookup: ``action=getLocalFileByUrl``."""

from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.responses import success_response
from jcpy.services.resolve_url import resolve_file_by_url, url_pathname
from jcpy.validation import Issue, string_field

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.services.resolve_url import ResolvedFile
    from jcpy.types import JsonObject

EMPTY_URL = "Empty url"
FILE_NOT_FOUND = "File does not exist"


def validate(data: JsonObject) -> list[Issue]:
    """Check ``getLocalFileByUrl`` parameters like the original schema.

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    return string_field(data, "url", required=True)


async def get_local_file_by_url_handler(context: ActionContext) -> Response:
    """Find which source file a public URL points to.

    Every source is tried in order; the first one holding the file
    wins.

    Args:
        context: Action context.

    Returns:
        ``{"path": "/dir", "name": "file.png", "source": "name"}``.

    Raises:
        HttpError: ``400 Empty url`` for a missing or invalid URL,
            ``400 File does not exist`` when no source has the file.
    """
    data = context.params.data
    url = data.get("url")
    if (
        validate(data)
        or not isinstance(url, str)
        or not url.strip()
        or url_pathname(url) is None
    ):
        raise HttpError.bad_request(EMPTY_URL)

    try:
        sources = await context.sources.get_sources(
            "", context.role, context.params.action, context.access
        )
    except Exception:
        raise HttpError.bad_request(FILE_NOT_FOUND) from None

    resolved: ResolvedFile | None = None
    for source in sources:
        try:
            resolved = await resolve_file_by_url(source, url)
        except Exception:  # noqa: S112 - try the next source
            continue
        if resolved is not None:
            break
    if resolved is None:
        raise HttpError.bad_request(FILE_NOT_FOUND)

    return success_response(
        {
            "path": resolved.path,
            "name": resolved.name,
            "source": resolved.source,
        }
    )
