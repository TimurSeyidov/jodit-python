"""``action=imageSave``."""

import posixpath
from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.responses import success_response
from jcpy.services.images import save_image
from jcpy.v1.common import first_source
from jcpy.v1.images_common import validate_named
from jcpy.validation import require_valid

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext


async def image_save_handler(context: ActionContext) -> Response:
    """Store the image produced by the client-side image editor.

    The edited image is the first uploaded file (``defaultFilesKey`` or
    ``files[...]`` field); it is saved as ``newname`` or over ``name``.

    Args:
        context: Action context.

    Returns:
        ``{"newPath": "<baseurl><path>", "name": "<file name>"}``.

    Raises:
        HttpError: ``405`` for non-POST requests, ``400`` for invalid
            parameters, missing or invalid image data, ``403`` without
            permission, ``404`` for a missing source or path.
    """
    if context.request.method != "POST":
        raise HttpError.method_not_allowed("imageSave requires a POST request")
    params = context.params
    require_valid(validate_named(params.data, name_required=False))
    source = await first_source(context)
    files_key = (
        source.settings.default_files_key or context.config.default_files_key
    )
    uploads = [
        item.file
        for item in params.files
        if item.field == files_key or item.field.startswith("files[")
    ]
    if not uploads:
        raise HttpError.bad_request("No image has been uploaded")
    await context.access.check_permission(
        context.role, params.action, await source.get_path(params.path)
    )
    name = params.get_str("name", "")
    new_name = params.get_str("newname", "")
    if not name and not new_name:
        raise HttpError.bad_request('Either "name" or "newname" is required')

    written = await save_image(
        context, source, await uploads[0].read(), name, new_name, params.path
    )
    return success_response(
        {
            "newPath": source.settings.baseurl + written,
            "name": posixpath.basename(written),
        }
    )
