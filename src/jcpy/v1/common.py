"""Helpers shared by action handlers."""

from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.responses import success_response
from jcpy.sources import SOURCE_NOT_FOUND
from jcpy.validation import string_field

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.sources import Source
    from jcpy.types import JsonObject
    from jcpy.validation import Issue


async def first_source(context: ActionContext) -> Source:
    """Select the source an action works on.

    Args:
        context: Action context.

    Returns:
        The requested source, or the first one when none is named.

    Raises:
        HttpError: ``404 Source not found``.
    """
    sources = await context.get_sources()
    if not sources:
        raise HttpError.not_found(SOURCE_NOT_FOUND)
    return sources[0]


def string_fields(
    data: JsonObject, *, required: tuple[str, ...] = ()
) -> list[Issue]:
    """Validate optional ``source``/``path`` and required string fields.

    Args:
        data: Request parameters.
        required: Names of mandatory string fields.

    Returns:
        Issues in schema order.
    """
    return [
        *string_field(data, "source", required=False),
        *string_field(data, "path", required=False),
        *(
            issue
            for name in required
            for issue in string_field(data, name, required=True)
        ),
    ]


def required_text(context: ActionContext, name: str, label: str) -> str:
    """Read a non-empty string parameter.

    Args:
        context: Action context.
        name: Parameter name.
        label: Capitalized name used in the error message.

    Returns:
        Parameter value.

    Raises:
        HttpError: ``400 <label> parameter is required`` when empty.
    """
    value = context.params.get_str(name, "")
    if not value:
        msg = f"{label} parameter is required"
        raise HttpError.bad_request(msg)
    return value


def done() -> Response:
    """Build the bare success response.

    Returns:
        ``{"success": true, "data": {"code": 220}}``.
    """
    return success_response({})
