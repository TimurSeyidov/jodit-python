"""``action=generateDocx``."""

import logging
from typing import TYPE_CHECKING

from starlette.responses import Response

from jcpy.documents.resources import ResourcePolicy
from jcpy.errors import HttpError
from jcpy.optional import optional_feature
from jcpy.v1.documents_common import html_issues, require_html
from jcpy.validation import Issue, require_valid

if TYPE_CHECKING:
    from jcpy.context import ActionContext
    from jcpy.types import JsonObject

logger = logging.getLogger("jcpy")

DOCX_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def validate(data: JsonObject) -> list[Issue]:
    """Check parameters like the original zod schema.

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    return html_issues(data)


async def generate_docx_handler(context: ActionContext) -> Response:
    """Convert ``html`` into a Word document attachment.

    Args:
        context: Action context.

    Returns:
        DOCX response named ``document.docx``.

    Raises:
        HttpError: ``400`` for invalid parameters or blank HTML,
            ``501`` without the ``docx`` extra, ``500 Failed to generate
            DOCX`` when conversion fails.
    """
    data = context.params.data
    require_valid(validate(data))
    html = require_html(data)
    with optional_feature("docx", "generateDocx"):
        from jcpy.documents.docx import html_to_docx

    try:
        document = await html_to_docx(
            html, ResourcePolicy.from_config(context.config)
        )
    except Exception as error:
        logger.exception("Failed to generate DOCX")
        raise HttpError(500, "Failed to generate DOCX") from error
    return Response(
        document,
        media_type=DOCX_TYPE,
        headers={
            "Expires": "0",
            "Cache-Control": "must-revalidate, post-check=0, pre-check=0",
            "Content-Disposition": "attachment;filename=document.docx",
        },
    )
