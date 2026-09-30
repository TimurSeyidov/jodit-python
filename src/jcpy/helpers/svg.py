"""Removal of active content from uploaded SVG images.

An SVG opened directly runs its scripts with the privileges of the site
serving it. The document is parsed without entities or external
references, active parts are dropped and it is written out again, so
anything the parser skips (processing instructions such as
``<?xml-stylesheet?>``, the DOCTYPE, comments) is gone as well.
"""

import re
import xml.etree.ElementTree as ElementTree

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XHTML_NS = "http://www.w3.org/1999/xhtml"

_REMOVED_ELEMENTS = frozenset(
    {
        "script",
        "foreignobject",
        "iframe",
        "embed",
        "object",
        "handler",
        "listener",
    }
)
"""Elements dropped with their content (lower-case local names)."""

_ANIMATIONS = frozenset(
    {"set", "animate", "animatemotion", "animatetransform", "animatecolor"}
)
"""Elements that can change other attributes, e.g. ``href``."""

_URL_ATTRIBUTES = frozenset({"href", "src", "action", "formaction"})
"""Attributes holding a URL (``xlink:href`` included)."""

_ANIMATION_VALUES = ("to", "from", "by", "values")
"""Attributes of an animation holding the values it sets."""

_SAFE_DATA = re.compile(r"^data:image/(png|jpe?g|gif|webp)[;,]")
"""``data:`` URLs of raster images, the only ones kept."""

_INVISIBLE = re.compile(r"[\x00-\x20\x7f]+")
"""Characters browsers ignore inside a URL scheme."""


class InvalidSvgError(ValueError):
    """The upload is not an SVG image that can be made safe."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"File is not a valid SVG image: {reason}")


def _local(name: str) -> str:
    return name.rpartition("}")[2].lower()


def _namespace(name: str) -> str:
    return name[1:].partition("}")[0] if name.startswith("{") else ""


def is_unsafe_url(value: str) -> bool:
    """Tell whether a URL could run a script when followed or loaded.

    Args:
        value: Attribute value.

    Returns:
        ``True`` for ``javascript:``, ``vbscript:`` and ``data:`` URLs
        other than raster images, however they are spaced or cased.
    """
    compact = _INVISIBLE.sub("", value).lower()
    if compact.startswith(("javascript:", "vbscript:")):
        return True
    return compact.startswith("data:") and not _SAFE_DATA.match(compact)


def _unsafe_animation(element: ElementTree.Element) -> bool:
    target = ""
    for name, value in element.attrib.items():
        if _local(name) == "attributename":
            target = value.strip().lower().rpartition(":")[2]
    if target in _URL_ATTRIBUTES or target.startswith("on"):
        return True
    # "values" is a ";"-separated list: every item counts.
    return any(
        is_unsafe_url(item)
        for name, value in element.attrib.items()
        if _local(name) in _ANIMATION_VALUES
        for item in value.split(";")
    )


def _removed(element: ElementTree.Element) -> bool:
    local = _local(element.tag)
    if local in _REMOVED_ELEMENTS or _namespace(element.tag) == XHTML_NS:
        return True
    return local in _ANIMATIONS and _unsafe_animation(element)


def _clean(element: ElementTree.Element) -> None:
    """Remove unsafe attributes and children, recursively."""
    for name, value in list(element.attrib.items()):
        local = _local(name)
        if local.startswith("on") or (
            local in _URL_ATTRIBUTES and is_unsafe_url(value)
        ):
            del element.attrib[name]
    for child in list(element):
        if _removed(child):
            element.remove(child)
        else:
            _clean(child)


def _plain_names(root: ElementTree.Element) -> None:
    """Write SVG and XLink names the way editors do.

    ElementTree would invent ``ns0:`` prefixes, or take ones other code
    registered globally; SVG names become unprefixed under
    ``xmlns="..."`` on the root and XLink names ``xlink:...``.
    """
    svg = f"{{{SVG_NS}}}"
    xlink = f"{{{XLINK_NS}}}"
    uses_xlink = False
    for element in root.iter():
        if element.tag.startswith(svg):
            element.tag = element.tag[len(svg) :]
        for name in [key for key in element.attrib if key.startswith("{")]:
            value = element.attrib.pop(name)
            if name.startswith(xlink):
                element.attrib[f"xlink:{name[len(xlink) :]}"] = value
                uses_xlink = True
            elif name.startswith(svg):
                element.attrib[name[len(svg) :]] = value
            else:
                element.attrib[name] = value
    root.set("xmlns", SVG_NS)
    if uses_xlink:
        root.set("xmlns:xlink", XLINK_NS)


def sanitize_svg(data: bytes) -> bytes:
    """Return an SVG image without scripts or script-running links.

    Args:
        data: Uploaded file contents.

    Returns:
        The image re-encoded as UTF-8 XML.

    Raises:
        InvalidSvgError: The data is not well-formed XML, declares
            entities, references external ones, or its root element is
            not ``<svg>``.
    """
    try:
        root = fromstring(data, forbid_dtd=False)
    except DefusedXmlException as error:
        raise InvalidSvgError(type(error).__name__) from None
    except ElementTree.ParseError as error:
        raise InvalidSvgError(str(error)) from None
    if root.tag != f"{{{SVG_NS}}}svg":
        raise InvalidSvgError("the root element is not <svg>")
    _clean(root)
    _plain_names(root)
    text = ElementTree.tostring(root, encoding="unicode")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + text.encode()
