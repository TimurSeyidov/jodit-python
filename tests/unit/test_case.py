"""Case conversion against reference ``change-case`` outputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from jcpy.helpers.case import camel_case, constant_case

FIXTURES = Path(__file__).parent.parent / "fixtures" / "case_cases.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURES.read_text())


@pytest.mark.parametrize(
    "case", CASES, ids=[str(index) for index in range(len(CASES))]
)
def test_matches_change_case(case: dict[str, Any]) -> None:
    assert constant_case(case["input"]) == case["constant"]
    assert camel_case(case["input"]) == case["camel"]
