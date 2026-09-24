"""HTML to PDF with WeasyPrint."""

from typing import TYPE_CHECKING, Any, Literal

from anyio import from_thread, to_thread
from weasyprint import CSS, HTML
from weasyprint.urls import URLFetcher, URLFetcherResponse

from jcpy.documents.resources import is_remote, load_remote

if TYPE_CHECKING:
    from jcpy.documents.resources import ResourcePolicy

type PaperFormat = Literal["A4", "A3", "Letter", "Legal", "Tabloid"]
type Orientation = Literal["portrait", "landscape"]

PAPER_SIZES: dict[str, tuple[str, str]] = {
    "A4": ("210mm", "297mm"),
    "A3": ("297mm", "420mm"),
    "Letter": ("8.5in", "11in"),
    "Legal": ("8.5in", "14in"),
    "Tabloid": ("11in", "17in"),
}
MARGIN = "1cm"


class GuardedFetcher(URLFetcher):  # type: ignore[misc]
    """WeasyPrint fetcher: ``data:`` inline, network through the policy.

    ``http``/``https`` resources are downloaded by the connector (SSRF
    checks, size limit); every other scheme, ``file:`` included, is
    refused. Refused resources are skipped by WeasyPrint.

    Args:
        policy: Loading policy.
    """

    def __init__(self, policy: ResourcePolicy) -> None:
        super().__init__(allowed_protocols={"data"})
        self.policy = policy

    def fetch(self, url: str, headers: Any = None) -> URLFetcherResponse:  # noqa: ANN401
        """Fetch one resource of the document.

        Args:
            url: Absolute resource URL.
            headers: Request headers proposed by WeasyPrint (ignored for
                remote resources).

        Returns:
            Resource response.
        """
        if not is_remote(url):
            return super().fetch(url, headers)
        fetched = from_thread.run(load_remote, url, self.policy)
        response_headers = (
            {"Content-Type": fetched.content_type}
            if fetched.content_type
            else {}
        )
        return URLFetcherResponse(fetched.url, fetched.body, response_headers)


def page_style(paper: str, orientation: str) -> str:
    """Build the ``@page`` rule applied on top of the document styles.

    Args:
        paper: Paper format name.
        orientation: ``portrait`` or ``landscape``.

    Returns:
        CSS with the page size and 1 cm margins.
    """
    width, height = PAPER_SIZES[paper]
    if orientation == "landscape":
        width, height = height, width
    return f"@page {{ size: {width} {height}; margin: {MARGIN}; }}"


def _render(html: str, style: str, policy: ResourcePolicy) -> bytes:
    fetcher = GuardedFetcher(policy)
    document = HTML(string=html, url_fetcher=fetcher)
    pdf: bytes = document.write_pdf(stylesheets=[CSS(string=style)])
    return pdf


async def html_to_pdf(
    html: str,
    policy: ResourcePolicy,
    paper: PaperFormat = "A4",
    orientation: Orientation = "portrait",
) -> bytes:
    """Render HTML as a PDF document.

    Backgrounds are printed; scripts are not executed.

    Args:
        html: Document markup.
        policy: How remote resources may be loaded.
        paper: Paper format.
        orientation: Page orientation.

    Returns:
        PDF bytes.
    """
    style = page_style(paper, orientation)
    return await to_thread.run_sync(_render, html, style, policy)
