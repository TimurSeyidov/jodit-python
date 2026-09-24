"""HTML to DOCX with html-for-docx."""

import base64
import binascii
import logging
from io import BytesIO

from anyio import to_thread
from bs4 import BeautifulSoup
from docx import Document
from docx.shared import Inches
from html4docx import HtmlToDocx
from PIL import Image

from jcpy.documents.resources import ResourcePolicy, is_remote, load_remote

logger = logging.getLogger("jcpy")

MARGIN = Inches(0.5)
_DOCX_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "GIF", "BMP", "TIFF"})
_STRIPPED_TAGS = ("style", "script", "link")


def _as_docx_image(contents: bytes) -> bytes | None:
    """Return image bytes python-docx can embed (others become PNG)."""
    try:
        with Image.open(BytesIO(contents)) as image:
            if image.format in _DOCX_IMAGE_FORMATS:
                return contents
            output = BytesIO()
            image.save(output, "PNG")
            return output.getvalue()
    except Exception:
        return None


def _data_uri(contents: bytes) -> str | None:
    image = _as_docx_image(contents)
    if image is None:
        return None
    return "data:image/png;base64," + base64.b64encode(image).decode()


def _decode_data_uri(src: str) -> bytes | None:
    header, _, payload = src.partition(",")
    if not header.lower().startswith("data:image/") or ";base64" not in header:
        return None
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error:
        return None


async def _image_source(src: str, policy: ResourcePolicy) -> str | None:
    """Turn an ``<img src>`` into an embeddable data URI or nothing."""
    if src.lower().startswith("data:"):
        contents = _decode_data_uri(src)
        return None if contents is None else _data_uri(contents)
    if not is_remote(src):
        return None
    try:
        fetched = await load_remote(src, policy)
    except Exception as error:
        logger.warning("Image skipped in DOCX: %s", error)
        return None
    return _data_uri(fetched.body)


async def sanitize_html(html: str, policy: ResourcePolicy) -> str:
    """Prepare HTML so the converter never touches network or disk.

    ``<style>``, ``<script>`` and ``<link>`` are removed; every image is
    downloaded through the policy (or decoded from its ``data:`` URI)
    and inlined as a PNG/JPEG/... data URI; images that cannot be
    loaded that way are removed.

    Args:
        html: Document markup.
        policy: How remote resources may be loaded.

    Returns:
        Safe markup.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_STRIPPED_TAGS)):
        tag.decompose()
    for image in soup.find_all("img"):
        source = image.get("src")
        inline = (
            await _image_source(source, policy)
            if isinstance(source, str)
            else None
        )
        if inline is None:
            image.decompose()
        else:
            image["src"] = inline
    return str(soup)


def _convert(html: str) -> bytes:
    document = Document()
    for section in document.sections:
        section.top_margin = MARGIN
        section.right_margin = MARGIN
        section.bottom_margin = MARGIN
        section.left_margin = MARGIN
    HtmlToDocx().add_html_to_document(html, document)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


async def html_to_docx(html: str, policy: ResourcePolicy) -> bytes:
    """Convert HTML into a Word document with 0.5 inch margins.

    Args:
        html: Document markup.
        policy: How remote images may be loaded.

    Returns:
        DOCX bytes.
    """
    safe_html = await sanitize_html(html, policy)
    return await to_thread.run_sync(_convert, safe_html)
