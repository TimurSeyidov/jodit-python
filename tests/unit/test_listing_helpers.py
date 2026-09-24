"""Sorting, URL parsing and thumbnail rendering."""

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from PIL import Image

from jcpy.services.listing import _Item, sort_items
from jcpy.services.resolve_url import url_pathname
from jcpy.services.thumbs import render_thumbnail
from jcpy.storage.base import StatEntry

FIXTURES = Path(__file__).parent.parent / "fixtures"
SORT_CASES = json.loads((FIXTURES / "sort_cases.json").read_text())
URL_CASES = json.loads((FIXTURES / "url_cases.json").read_text())


@pytest.mark.parametrize(
    "case", SORT_CASES, ids=[str(index) for index in range(len(SORT_CASES))]
)
def test_sort_matches_v8(case: dict[str, Any]) -> None:
    items = [
        _Item(
            StatEntry(str(item["id"]), not item["isDirectory"]),
            item["name"],
            item["size"],
            item["mtime"],
            is_image=False,
        )
        for item in case["items"]
    ]

    sort_items(items, case["sortBy"], case["foldersPosition"])

    assert [int(item.entry.path) for item in items] == case["order"]


@pytest.mark.parametrize(
    "case", URL_CASES, ids=[repr(c["url"]) for c in URL_CASES]
)
def test_url_pathname_matches_whatwg(case: dict[str, Any]) -> None:
    # Paths are compared decoded: the connector decodes them anyway.
    pathname = url_pathname(case["url"])
    expected = case["pathname"]

    if expected is None:
        assert pathname is None
    else:
        assert pathname is not None
        assert unquote(pathname) == unquote(expected)


@pytest.mark.parametrize("url", ["http://[::1/x", "http://[::1]x/"])
def test_url_pathname_rejects_bad_ipv6(url: str) -> None:
    assert url_pathname(url) is None


def image_bytes(mode: str, size: tuple[int, int], fmt: str) -> bytes:
    output = BytesIO()
    Image.new(mode, size, "red").save(output, fmt)
    return output.getvalue()


@pytest.mark.parametrize(
    ("extension", "source_format", "mode", "expected"),
    [
        ("png", "PNG", "RGBA", "PNG"),
        ("webp", "WEBP", "RGB", "WEBP"),
        ("gif", "GIF", "P", "GIF"),
        ("jpg", "PNG", "RGBA", "JPEG"),
        ("bmp", "BMP", "RGB", "JPEG"),
        ("jpeg", "JPEG", "L", "JPEG"),
    ],
)
def test_render_thumbnail_keeps_format(
    extension: str, source_format: str, mode: str, expected: str
) -> None:
    thumb = render_thumbnail(
        image_bytes(mode, (600, 300), source_format), extension, 250, 90
    )

    with Image.open(BytesIO(thumb)) as image:
        assert image.format == expected
        assert image.size == (250, 125)


def test_render_thumbnail_does_not_enlarge() -> None:
    thumb = render_thumbnail(
        image_bytes("RGB", (40, 20), "PNG"), "png", 250, 90
    )

    with Image.open(BytesIO(thumb)) as image:
        assert image.size == (40, 20)


def test_render_thumbnail_rejects_non_images() -> None:
    with pytest.raises(OSError, match="cannot identify image"):
        render_thumbnail(b"not an image", "png", 250, 90)
