"""Removal of active content from SVG uploads."""

from xml.etree import ElementTree

import pytest
from defusedxml.ElementTree import fromstring

from jcpy.helpers.svg import (
    SVG_NS,
    InvalidSvgError,
    is_unsafe_url,
    sanitize_svg,
)

HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink">'
)


def clean(body: str) -> str:
    return sanitize_svg(f"{HEAD}{body}</svg>".encode()).decode()


def parsed(text: str) -> ElementTree.Element:
    return fromstring(text.split("\n", 1)[1])


@pytest.mark.parametrize(
    "body",
    [
        "<script>alert(1)</script>",
        '<script xlink:href="https://evil.example/x.js"/>',
        "<SCRIPT>alert(1)</SCRIPT>",
        '<foreignObject><body xmlns="http://www.w3.org/1999/xhtml">'
        "<script>alert(1)</script></body></foreignObject>",
        '<h:script xmlns:h="http://www.w3.org/1999/xhtml">alert(1)</h:script>',
        '<h:img xmlns:h="http://www.w3.org/1999/xhtml" src="x"/>',
        '<iframe src="https://evil.example"/>',
        '<embed src="x.swf"/>',
        '<object data="x.swf"/>',
        '<handler type="application/ecmascript">alert(1)</handler>',
        '<set attributeName="href" to="javascript:alert(1)"/>',
        '<set attributeName="onmouseover" to="alert(1)"/>',
        '<animate attributeName="xlink:href" values="javascript:alert(1)"/>',
        '<animate attributeName="fill" values="red;javascript:alert(1)"/>',
    ],
)
def test_active_elements_are_removed(body: str) -> None:
    result = clean(f"{body}<rect width='1'/>")

    assert "alert" not in result
    assert "evil" not in result
    assert "script" not in result.lower()
    assert "<rect" in result


@pytest.mark.parametrize(
    ("body", "gone"),
    [
        ('<rect onload="alert(1)"/>', "onload"),
        ('<rect ONCLICK="alert(1)"/>', "onclick"),
        ('<a href="javascript:alert(1)"><rect/></a>', "javascript"),
        ('<a xlink:href="javascript:alert(1)"><rect/></a>', "javascript"),
        ('<a href=" JaVaScRiPt:alert(1)"><rect/></a>', "alert"),
        ('<a href="java&#x09;script:alert(1)"><rect/></a>', "alert"),
        ('<a href="&#x6A;avascript:alert(1)"><rect/></a>', "alert"),
        ('<a href="vbscript:msgbox(1)"><rect/></a>', "vbscript"),
        (
            '<image href="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="/>',
            "data:image/svg",
        ),
        ('<a href="data:text/html,&lt;script&gt;"><rect/></a>', "text/html"),
    ],
)
def test_unsafe_attributes_are_removed(body: str, gone: str) -> None:
    result = clean(body)

    assert gone.lower() not in result.lower()


def test_safe_content_is_kept() -> None:
    body = (
        '<defs><linearGradient id="g"><stop offset="0" stop-color="red"/>'
        "</linearGradient></defs>"
        "<style>.a { fill: url(#g); }</style>"
        '<g class="a" transform="translate(1 2)"><path d="M0 0L10 10"/></g>'
        '<a href="https://example.com/"><text x="1">Привет</text></a>'
        '<use xlink:href="#g"/>'
        '<image href="data:image/png;base64,iVBORw0KGgo="/>'
        '<animate attributeName="opacity" values="0;1" dur="1s"/>'
    )

    root = parsed(clean(body))

    tags = {element.tag.rpartition("}")[2] for element in root.iter()}
    assert tags >= {
        "svg",
        "linearGradient",
        "stop",
        "style",
        "path",
        "a",
        "text",
        "use",
        "image",
        "animate",
    }
    assert root.find(f".//{{{SVG_NS}}}text").text == "Привет"  # type: ignore[union-attr]
    assert "https://example.com/" in clean(body)


def test_editor_exports_are_accepted() -> None:
    illustrator = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<!-- Generator: Adobe Illustrator -->\n"
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
        b'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" '
        b'viewBox="0 0 10 10"><circle r="5"/></svg>'
    )
    inkscape = (
        b'<svg xmlns="http://www.w3.org/2000/svg" '
        b'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        b'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/'
        b'sodipodi-0.dtd"><sodipodi:namedview inkscape:zoom="1"/>'
        b'<g inkscape:label="Layer 1"><rect width="1" height="1"/></g></svg>'
    )

    for data in (illustrator, inkscape):
        result = sanitize_svg(data)

        assert result.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
        assert b"DOCTYPE" not in result
        assert parsed(result.decode()).tag == f"{{{SVG_NS}}}svg"


def test_output_ignores_prefixes_registered_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Other code (PDF rendering) may register its own prefix for SVG.
    registry = ElementTree._namespace_map  # type: ignore[attr-defined]
    monkeypatch.setitem(registry, SVG_NS, "svg")

    result = clean('<a xlink:href="#x"><rect/></a>')

    assert '<svg xmlns="http://www.w3.org/2000/svg"' in result
    assert '<a xlink:href="#x"><rect /></a>' in result


def test_prefixed_svg_names_become_plain() -> None:
    data = (
        b'<s:svg xmlns:s="http://www.w3.org/2000/svg">'
        b'<s:rect s:width="3"/></s:svg>'
    )

    result = sanitize_svg(data).decode()

    assert '<svg xmlns="http://www.w3.org/2000/svg"><rect width="3" />' in (
        result
    )


def test_processing_instructions_are_dropped() -> None:
    data = (
        b'<?xml-stylesheet type="text/xsl" href="evil.xsl"?>'
        + f"{HEAD}<rect/></svg>".encode()
    )

    assert b"evil.xsl" not in sanitize_svg(data)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"not xml", "syntax"),
        (b"<svg><rect></svg>", "mismatched"),
        (b'<html xmlns="http://www.w3.org/1999/xhtml"/>', "root element"),
        (b"<svg/>", "root element"),
        (
            b'<!DOCTYPE svg [<!ENTITY x "y">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
            "EntitiesForbidden",
        ),
        (
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
            "EntitiesForbidden",
        ),
        (
            b'<!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg">&b;</svg>',
            "EntitiesForbidden",
        ),
    ],
)
def test_invalid_or_hostile_documents(data: bytes, reason: str) -> None:
    with pytest.raises(InvalidSvgError, match=reason):
        sanitize_svg(data)


def test_elements_outside_any_namespace() -> None:
    data = f"{HEAD}<g xmlns=''><rect/></g></svg>".encode()

    result = sanitize_svg(data).decode()

    assert parsed(result).tag == f"{{{SVG_NS}}}svg"
    assert "<rect" in result


@pytest.mark.parametrize(
    ("url", "unsafe"),
    [
        ("javascript:x", True),
        ("  JAVA\tSCRIPT:x", True),
        ("vbscript:x", True),
        ("data:text/html,x", True),
        ("data:image/svg+xml,x", True),
        ("data:image/png;base64,x", False),
        ("data:image/jpeg,x", False),
        ("https://example.com/javascript:", False),
        ("#id", False),
    ],
)
def test_is_unsafe_url(url: str, unsafe: bool) -> None:
    assert is_unsafe_url(url) is unsafe
