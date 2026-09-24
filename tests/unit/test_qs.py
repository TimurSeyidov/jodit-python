"""Bracket-notation parsing against reference ``qs`` outputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from jcpy.helpers.qs import QsDepthError, QsOptions, parse

FIXTURES = Path(__file__).parent.parent / "fixtures" / "qs_cases.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURES.read_text())


def _body_options(text: str) -> QsOptions:
    return QsOptions(
        allow_prototypes=True,
        array_limit=max(100, len(text.split("&"))),
        depth=32,
        strict_depth=True,
    )


@pytest.mark.parametrize(
    "case", CASES, ids=[str(index) for index in range(len(CASES))]
)
def test_matches_qs_with_query_defaults(case: dict[str, Any]) -> None:
    assert parse(case["input"]) == case["query"]["result"]


@pytest.mark.parametrize(
    "case", CASES, ids=[str(index) for index in range(len(CASES))]
)
def test_matches_qs_with_body_parser_options(case: dict[str, Any]) -> None:
    options = _body_options(case["input"])

    if "error" in case["body"]:
        with pytest.raises(QsDepthError):
            parse(case["input"], options)
    else:
        assert parse(case["input"], options) == case["body"]["result"]


def test_keeps_object_key_order_like_javascript() -> None:
    assert list(parse("b=1&1=a&0=z")) == ["0", "1", "b"]


def test_depth_zero_keeps_whole_key() -> None:
    options = QsOptions(depth=0)

    assert parse("a[b]=1&toString=2", options) == {"a[b]": "1"}
    assert parse("toString=2", QsOptions(depth=0, allow_prototypes=True)) == {
        "toString": "2"
    }
