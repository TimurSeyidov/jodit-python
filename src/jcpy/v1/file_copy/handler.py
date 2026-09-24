"""``action=fileCopy``."""

from typing import TYPE_CHECKING

from jcpy.services.operations import copy_path
from jcpy.v1.common import done, first_source, required_text, string_fields
from jcpy.validation import require_valid_plain

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext


async def file_copy_handler(context: ActionContext) -> Response:
    """Copy a file or folder from (relative to the root) into path.

    Args:
        context: Action context.

    Returns:
        ``{"code": 220}``.

    Raises:
        HttpError: ``400``, ``403`` or ``404`` as described by
            ``copy_path``.
    """
    require_valid_plain(string_fields(context.params.data, required=("from",)))
    source = await first_source(context)
    from_path = required_text(context, "from", "From")
    await copy_path(context, source, from_path, context.params.path)
    return done()
