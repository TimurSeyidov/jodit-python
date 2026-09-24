"""``action=imageCrop``."""

from typing import TYPE_CHECKING

from jcpy.responses import success_response
from jcpy.services.images import crop_image
from jcpy.v1.common import first_source, required_text
from jcpy.v1.images_common import validate_edit
from jcpy.validation import require_valid

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext


async def image_crop_handler(context: ActionContext) -> Response:
    """Cut box[x], box[y], box[w], box[h] out of name.

    The result replaces ``name`` or is stored as ``newname``.

    Args:
        context: Action context.

    Returns:
        ``{"newPath": "<baseurl><path of the written image>"}``.

    Raises:
        HttpError: ``400`` for invalid parameters or unprocessable
            images, ``403`` without permission, ``404`` for a
            missing source or image.
    """
    params = context.params
    issues, box = validate_edit(params.data, ("x", "y", "w", "h"))
    require_valid(issues)
    source = await first_source(context)
    name = required_text(context, "name", "Name")
    written = await crop_image(
        context,
        source,
        name,
        box,
        params.get_str("newname", ""),
        params.path,
    )
    return success_response({"newPath": source.settings.baseurl + written})
