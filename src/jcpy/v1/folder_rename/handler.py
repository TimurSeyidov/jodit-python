"""``action=folderRename``."""

from typing import TYPE_CHECKING

from jcpy.services.operations import rename_path
from jcpy.v1.common import done, first_source, required_text, string_fields
from jcpy.validation import require_valid

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext


async def folder_rename_handler(context: ActionContext) -> Response:
    """Rename ``name`` to ``newname`` in the current directory.

    Args:
        context: Action context.

    Returns:
        ``{"code": 220}``.

    Raises:
        HttpError: ``400``, ``403`` or ``404`` as described by
            ``rename_path``.
    """
    params = context.params
    require_valid(string_fields(params.data, required=("name", "newname")))
    source = await first_source(context)
    name = required_text(context, "name", "Name")
    new_name = required_text(context, "newname", "Newname")
    await rename_path(context, source, name, new_name, params.path, "folder")
    return done()
