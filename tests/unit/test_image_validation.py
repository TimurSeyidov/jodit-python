"""Image action parameters against the original zod schemas."""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from jcpy.v1.images_common import validate_edit, validate_named

if TYPE_CHECKING:
    from collections.abc import Callable

    from jcpy.types import JsonObject
    from jcpy.validation import Issue

CASES = json.loads(
    (
        Path(__file__).parent.parent / "fixtures" / "image_schema_cases.json"
    ).read_text()
)
VALIDATORS: dict[
    str, Callable[[JsonObject], tuple[list[Issue], dict[str, int]]]
] = {
    "imageResize": lambda data: validate_edit(data, ("w", "h")),
    "imageCrop": lambda data: validate_edit(data, ("x", "y", "w", "h")),
    "imageSave": lambda data: (validate_named(data, name_required=False), {}),
    "imageLoad": lambda data: (validate_named(data, name_required=True), {}),
}


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[f"{c['schema']}|{json.dumps(c['input'])}" for c in CASES],
)
def test_matches_zod(case: dict[str, Any]) -> None:
    issues, box = VALIDATORS[case["schema"]](case["input"])

    assert [(issue.path, issue.message) for issue in issues] == [
        (issue["path"], issue["message"]) for issue in case.get("issues", [])
    ]
    if case["schema"] in {"imageResize", "imageCrop"} and "issues" not in case:
        assert box == case["box"]
