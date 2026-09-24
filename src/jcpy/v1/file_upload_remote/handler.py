"""``action=fileUploadRemote``."""

from typing import TYPE_CHECKING

from jcpy.helpers.urls import parse_url
from jcpy.responses import success_response
from jcpy.services.remote_upload import upload_from_url
from jcpy.v1.common import first_source, string_fields
from jcpy.validation import Issue, require_valid_plain, string_field

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.types import JsonObject


def validate(data: JsonObject) -> list[Issue]:
    """Check parameters like the original zod schema (``url`` required).

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    issues = [
        *string_fields(data),
        *string_field(data, "url", required=True),
    ]
    url = data.get("url")
    if isinstance(url, str) and parse_url(url) is None:
        issues.append(Issue("url", "Invalid URL"))
    return issues


async def file_upload_remote_handler(context: ActionContext) -> Response:
    """Download ``url`` into the current directory.

    Args:
        context: Action context.

    Returns:
        ``{"baseurl", "newfilename", "isImage"}``.

    Raises:
        HttpError: ``400`` for invalid parameters or failed downloads,
            ``403`` for refused hosts, types, sizes or permissions,
            ``404`` for an unknown source or path.
    """
    params = context.params
    require_valid_plain(validate(params.data))
    source = await first_source(context)
    url = params.get_str("url", "")
    stored = await upload_from_url(context, source, url, params.path)
    return success_response(
        {
            "baseurl": source.settings.baseurl,
            "newfilename": stored.name,
            "isImage": stored.is_image,
        }
    )
