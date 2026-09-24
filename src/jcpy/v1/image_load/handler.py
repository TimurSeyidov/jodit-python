"""``action=imageLoad``."""

from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.responses import success_response
from jcpy.services.images import load_image
from jcpy.v1.common import first_source, required_text
from jcpy.v1.images_common import validate_named
from jcpy.validation import require_valid

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext


async def image_load_handler(context: ActionContext) -> Response:
    """Return the image ``name`` as a data URL for the image editor.

    Args:
        context: Action context.

    Returns:
        ``{"content": "data:<mime>;base64,...", "name": "<file name>"}``.

    Raises:
        HttpError: ``405`` for non-POST requests, ``400`` for invalid
            parameters, ``403`` without permission, ``404`` for a
            missing source or image.
    """
    if context.request.method != "POST":
        raise HttpError.method_not_allowed("imageLoad requires a POST request")
    params = context.params
    require_valid(validate_named(params.data, name_required=True))
    source = await first_source(context)
    name = required_text(context, "name", "Name")
    content, file_name = await load_image(context, source, name, params.path)
    return success_response({"content": content, "name": file_name})
