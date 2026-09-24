"""Folder creation: ``action=folderCreate``."""

from typing import TYPE_CHECKING

from jcpy.responses import success_response
from jcpy.services.operations import make_folder
from jcpy.v1.common import first_source, required_text

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext


async def folder_create_handler(context: ActionContext) -> Response:
    """Create the sub-folder ``name`` in the current directory.

    Args:
        context: Action context.

    Returns:
        ``{"messages": ["Directory successfully created"]}``.

    Raises:
        HttpError: ``400``, ``403`` or ``404`` as described by
            ``make_folder``.
    """
    source = await first_source(context)
    name = required_text(context, "name", "Name")
    await make_folder(context, source, name, context.params.path)
    return success_response({"messages": ["Directory successfully created"]})
