"""Parameter conversion and lookup."""

import math
from typing import TYPE_CHECKING

import pytest

from jcpy.context import RequestContext, prepare_value

if TYPE_CHECKING:
    from jcpy.types import JsonValue


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("false", False),
        ("10", 10),
        ("1.5", 1.5),
        (" 5 ", 5),
        ("-3", -3),
        ("1e3", 1000),
        (".5", 0.5),
        ("5.", 5),
        ("0x1A", 0),
        ("0b11", 0),
        ("Infinity", math.inf),
        ("-Infinity", -math.inf),
        ("abc", "abc"),
        ("10px", "10px"),
        ("", ""),
        ("True", "True"),
        (None, None),
        (7, 7),
        (["1"], ["1"]),
    ],
)
def test_prepare_value(raw: JsonValue, expected: JsonValue) -> None:
    assert prepare_value(raw) == expected


def test_prepare_value_whitespace_is_nan() -> None:
    # JavaScript: +" " is 0 (numeric), parseFloat(" ") is NaN.
    value = prepare_value("  ")

    assert isinstance(value, float)
    assert math.isnan(value)


def test_get_field_nested_and_converted() -> None:
    context = RequestContext({"mods": {"offset": "10", "sortBy": "name"}})

    assert context.get_field("mods/offset", 0) == 10
    assert context.get_field("mods/sortBy", "changed") == "name"


def test_get_field_prefers_flat_bracket_key() -> None:
    context = RequestContext(
        {"mods[withFolders]": "true", "mods": {"withFolders": "false"}}
    )

    assert context.get_field("mods/withFolders", False) is True


def test_get_field_defaults() -> None:
    context = RequestContext({"mods": "plain", "list": ["a", "b"]})

    assert context.get_field("missing", "d") == "d"
    assert context.get_field("mods/offset", "5") == 5
    assert context.get_field("missing/deep/key", 3) == 3
    assert context.get_field("list/1") == "b"
    assert context.get_field("list/9", "x") == "x"
    assert context.get_field("list/a", "x") == "x"


def test_string_properties_keep_raw_text() -> None:
    context = RequestContext({"action": "files", "source": 12, "path": ["x"]})

    assert context.action == "files"
    assert context.source == "12"
    assert context.path == "/"


def test_string_property_defaults() -> None:
    context = RequestContext({})

    assert (context.action, context.source, context.path) == (
        "default",
        "",
        "/",
    )
    assert context.files == []
