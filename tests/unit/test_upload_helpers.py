"""File name and size helpers against reference npm/Node outputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from jcpy.helpers.js import (
    node_basename,
    node_extname,
    parse_bytes,
    sanitize_filename,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
UPLOAD = json.loads((FIXTURES / "upload_cases.json").read_text())
EXTNAME = json.loads((FIXTURES / "extname_cases.json").read_text())


@pytest.mark.parametrize(
    "case",
    UPLOAD["sanitize"],
    ids=[repr(c["name"][:20]) for c in UPLOAD["sanitize"]],
)
def test_sanitize_filename(case: dict[str, Any]) -> None:
    assert sanitize_filename(case["name"], "_") == case["underscore"]
    assert sanitize_filename(case["name"]) == case["plain"]


@pytest.mark.parametrize(
    "case", UPLOAD["bytes"], ids=[repr(c["value"]) for c in UPLOAD["bytes"]]
)
def test_parse_bytes(case: dict[str, Any]) -> None:
    assert parse_bytes(case["value"]) == case["result"]


@pytest.mark.parametrize(
    "case", EXTNAME, ids=[repr(c["path"]) for c in EXTNAME]
)
def test_node_extname_and_basename(case: dict[str, Any]) -> None:
    assert node_extname(case["path"]) == case["ext"]
    assert node_basename(case["path"], case["ext"]) == case["stem"]
    assert node_basename(case["path"]) == case["base"]
