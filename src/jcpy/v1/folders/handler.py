"""Folder listing: ``action=folders``."""

from typing import TYPE_CHECKING

from jcpy.responses import SUCCESS_CODE, JsonResponse
from jcpy.services.listing import list_folders
from jcpy.validation import (
    Issue,
    any_of,
    is_boolean,
    one_of,
    require_valid,
    string_field,
    union_field,
)

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.types import JsonObject, JsonValue

_DOTS = any_of(is_boolean, one_of("false", "true"))


def validate(data: JsonObject) -> list[Issue]:
    """Check ``folders`` parameters like the original zod schema.

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    return [
        *string_field(data, "source", required=False),
        *string_field(data, "path", required=False),
        *union_field(data, "dots", _DOTS),
    ]


async def folders_handler(context: ActionContext) -> Response:
    """List sub-folders of the requested path in the selected sources.

    Args:
        context: Action context.

    Returns:
        ``{"sources": [{name, title, baseurl, path, folders}, ...]}``;
        ``dots=false`` omits the leading ``.``/``..`` entry.

    Raises:
        HttpError: ``400`` for invalid parameters, ``404`` for an
            unknown source or path.
    """
    params = context.params
    require_valid(validate(params.data))
    dots = params.get_field("dots")
    sources: list[JsonValue] = [
        await list_folders(source, params.path, dots=dots)
        for source in await context.get_sources()
    ]
    return JsonResponse(
        {"success": True, "data": {"sources": sources, "code": SUCCESS_CODE}}
    )
