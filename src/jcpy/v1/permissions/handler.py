"""Permissions of the current user: ``action=permissions``."""

from typing import TYPE_CHECKING

from jcpy.acl import DEFAULT_RULES
from jcpy.helpers.case import camel_case
from jcpy.responses import success_response

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.types import JsonObject


async def permissions_handler(context: ActionContext) -> Response:
    """Report which actions the user may run in the requested path.

    Every action of ``DEFAULT_RULES`` is checked against the absolute
    path of the first selected source; a check that fails for any
    reason (including an invalid path) reports ``false``.

    Args:
        context: Action context.

    Returns:
        ``{"permissions": {"allowFiles": true, ...}}``.

    Raises:
        HttpError: ``404 Source not found`` for an unknown source.
    """
    sources = await context.get_sources()
    source = sources[0] if sources else None
    permissions: JsonObject = {}
    for action in DEFAULT_RULES:
        allowed = False
        if source is not None:
            try:
                path = await source.get_path(context.params.path)
                allowed = await context.access.is_allow(
                    context.role, action, path
                )
            except Exception:
                allowed = False
        permissions[camel_case(f"allow_{action}")] = allowed
    return success_response({"permissions": permissions})
