"""Multipart field parsing against reference ``append-field`` outputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from jcpy.helpers.append_field import build

FIXTURES = Path(__file__).parent.parent / "fixtures"
CASES: list[dict[str, Any]] = json.loads(
    (FIXTURES / "append_field_cases.json").read_text()
)


@pytest.mark.parametrize(
    "case", CASES, ids=[str(index) for index in range(len(CASES))]
)
def test_matches_append_field(case: dict[str, Any]) -> None:
    fields = [(key, value) for key, value in case["fields"]]

    assert build(fields) == case["result"]
