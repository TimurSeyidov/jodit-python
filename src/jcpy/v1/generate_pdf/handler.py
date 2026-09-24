"""``action=generatePdf``."""

import logging
from typing import TYPE_CHECKING, cast

from starlette.responses import Response

from jcpy.documents.resources import ResourcePolicy
from jcpy.errors import HttpError
from jcpy.optional import optional_feature
from jcpy.v1.documents_common import html_issues, require_html
from jcpy.validation import (
    Issue,
    any_of,
    is_string,
    object_of,
    one_of,
    require_valid,
    union_field,
)

if TYPE_CHECKING:
    from jcpy.context import ActionContext
    from jcpy.documents.pdf import Orientation, PaperFormat
    from jcpy.types import JsonObject

logger = logging.getLogger("jcpy")

_OPTIONS = object_of(
    {
        "format": one_of("A4", "A3", "Letter", "Legal", "Tabloid"),
        "page_orientation": one_of("portrait", "landscape"),
        "defaultFont": one_of("courier", "helvetica", "times"),
    }
)


def validate(data: JsonObject) -> list[Issue]:
    """Check parameters like the original zod schema.

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    return [
        *html_issues(data),
        *union_field(data, "options", any_of(is_string, _OPTIONS)),
    ]


async def generate_pdf_handler(context: ActionContext) -> Response:
    """Render ``html`` as a PDF attachment.

    ``options[format]`` (A4, A3, Letter, Legal, Tabloid) and
    ``options[page_orientation]`` select the page; margins are 1 cm.

    Args:
        context: Action context.

    Returns:
        ``application/pdf`` response named ``document.pdf``.

    Raises:
        HttpError: ``400`` for invalid parameters or blank HTML,
            ``501`` without the ``pdf`` extra (or Pango), ``500 Failed
            to generate PDF`` when rendering fails.
    """
    data = context.params.data
    require_valid(validate(data))
    html = require_html(data)
    options = data.get("options")
    paper, orientation = "A4", "portrait"
    if isinstance(options, dict):
        paper = str(options.get("format", paper))
        if options.get("page_orientation") == "landscape":
            orientation = "landscape"
    with optional_feature("pdf", "generatePdf", "install Pango"):
        from jcpy.documents.pdf import html_to_pdf

    try:
        pdf = await html_to_pdf(
            html,
            ResourcePolicy.from_config(context.config),
            cast("PaperFormat", paper),
            cast("Orientation", orientation),
        )
    except Exception as error:
        logger.exception("Failed to generate PDF")
        raise HttpError(500, "Failed to generate PDF") from error
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="document.pdf"'},
    )
