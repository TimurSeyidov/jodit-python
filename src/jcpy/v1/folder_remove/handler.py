"""Folder removal: ``action=folderRemove``."""

from typing import TYPE_CHECKING

from jcpy.services.operations import remove_folder
from jcpy.v1.common import done, first_source, required_text, string_fields
from jcpy.validation import require_valid

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext


async def folder_remove_handler(context: ActionContext) -> Response:
    """Delete the sub-folder ``name`` of the current directory.

    Args:
        context: Action context.

    Returns:
        ``{"code": 220}``.

    Raises:
        HttpError: ``400``, ``403`` or ``404`` as described by
            ``remove_folder``.
    """
    require_valid(string_fields(context.params.data, required=("name",)))
    source = await first_source(context)
    name = required_text(context, "name", "Name")
    await remove_folder(context, source, name, context.params.path)
    return done()
