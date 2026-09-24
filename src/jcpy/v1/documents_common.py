"""Parameter checks shared by the document actions."""

from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.validation import Issue, string_field

if TYPE_CHECKING:
    from jcpy.types import JsonObject

NEED_HTML = "Need html parameter"


def html_issues(data: JsonObject) -> list[Issue]:
    """Check ``html`` like ``z.string().min(1)``.

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    issues = string_field(data, "html", required=True)
    if not issues and data["html"] == "":
        issues.append(
            Issue("html", "Too small: expected string to have >=1 characters")
        )
    return issues


def require_html(data: JsonObject) -> str:
    """Return the HTML to convert.

    Args:
        data: Validated request parameters.

    Returns:
        Markup.

    Raises:
        HttpError: ``400 Need html parameter`` for blank markup.
    """
    html = data.get("html")
    if not isinstance(html, str) or not html.strip():
        raise HttpError.bad_request(NEED_HTML)
    return html
