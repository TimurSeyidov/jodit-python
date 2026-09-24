"""JavaScript helper ports against reference npm outputs."""

import json
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from jcpy.helpers.js import (
    format_bytes,
    format_datetime,
    is_js_numeric,
    js_slice,
    js_string_key,
    js_truthy,
    slugify,
)
from jcpy.helpers.svg_icon import generate_icon
from jcpy.storage.base import StatEntry
from jcpy.v1.file_download.handler import validate as download_issues
from jcpy.v1.files.handler import validate as files_issues
from jcpy.v1.folders.handler import validate as folders_issues
from jcpy.v1.get_local_file_by_url.handler import validate as url_issues
from jcpy.validation import MISSING, js_type

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from jcpy.types import JsonObject
    from jcpy.validation import Issue

FIXTURES = Path(__file__).parent.parent / "fixtures"
FORMAT = json.loads((FIXTURES / "format_cases.json").read_text())
ICONS = json.loads((FIXTURES / "icon_cases.json").read_text())
VALIDATORS: dict[str, Callable[[JsonObject], list[Issue]]] = {
    "files": files_issues,
    "folders": folders_issues,
    "fileDownload": download_issues,
    "getLocalFileByUrl": url_issues,
}


@pytest.fixture
def moscow_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "Europe/Moscow")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.parametrize(
    "case", FORMAT["bytes"], ids=[str(c["size"]) for c in FORMAT["bytes"]]
)
def test_format_bytes(case: dict[str, Any]) -> None:
    assert format_bytes(case["size"]) == case["result"]


@pytest.mark.usefixtures("moscow_time")
@pytest.mark.parametrize(
    "case",
    FORMAT["dayjs"],
    ids=[f"{c['format']}|{c['time']}" for c in FORMAT["dayjs"]],
)
def test_format_datetime(case: dict[str, Any]) -> None:
    assert format_datetime(case["time"], case["format"]) == case["result"]


@pytest.mark.parametrize(
    "case", FORMAT["slugify"], ids=[c["name"] for c in FORMAT["slugify"]]
)
def test_slugify(case: dict[str, Any]) -> None:
    assert slugify(case["name"]) == case["result"]


@pytest.mark.parametrize(
    "case",
    FORMAT["validation"],
    ids=[f"{c['schema']}|{c['input']}" for c in FORMAT["validation"]],
)
def test_validation_matches_zod(case: dict[str, Any]) -> None:
    issues = VALIDATORS[case["schema"]](case["input"])

    assert [(issue.path, issue.message) for issue in issues] == [
        (issue["path"], issue["message"]) for issue in case["issues"]
    ]


@pytest.mark.parametrize(
    "case", ICONS, ids=[f"{c['path']}|{c['width']}" for c in ICONS]
)
def test_generate_icon(case: dict[str, Any]) -> None:
    entry = StatEntry(case["path"], is_file=not case["isDirectory"])

    assert (
        generate_icon(entry, case["width"], case["height"]) == case["result"]
    )


def test_js_type() -> None:
    assert js_type(MISSING) == "undefined"
    assert js_type(1.5) == "number"


@pytest.mark.parametrize(
    ("value", "truthy"),
    [
        (math.nan, False),
        (0, False),
        ("", False),
        ([], True),
        ({}, True),
        ("0", True),
        (None, False),
    ],
)
def test_js_truthy(value: object, truthy: bool) -> None:
    assert js_truthy(value) is truthy


def test_is_js_numeric_uses_js_whitespace() -> None:
    assert is_js_numeric(chr(0xFEFF) + "5" + chr(0x2028))
    assert not is_js_numeric("\x1c5")


def test_js_slice() -> None:
    items = list(range(5))

    assert js_slice(items, 1.9, 3.1) == [1, 2]
    assert js_slice(items, -2, math.inf) == [3, 4]
    assert js_slice(items, -math.inf, 2) == [0, 1]


def test_js_string_order_uses_utf16_units() -> None:
    # U+FFFF sorts after U+1F600 in code points but before in UTF-16.
    assert js_string_key("￿") > js_string_key("😀")


@pytest.mark.parametrize(
    ("value", "name"),
    [
        (MISSING, "undefined"),
        (None, "null"),
        (True, "boolean"),
        (1, "number"),
        (1.5, "number"),
        ("s", "string"),
        ([], "array"),
        ({}, "object"),
    ],
)
def test_js_type_names(value: object, name: str) -> None:
    assert js_type(value) == name
