"""OpenAPI document."""

from typing import Any

import pytest
from openapi_spec_validator import validate

from jcpy.openapi.spec import ACTIONS as DOCS
from jcpy.openapi.spec import build_openapi
from jcpy.v1 import ACTIONS


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return build_openapi()


def test_document_is_valid_openapi(spec: dict[str, Any]) -> None:
    validate(spec)


def test_every_action_is_documented(spec: dict[str, Any]) -> None:
    documented = {path.removeprefix("/") for path in spec["paths"]}

    assert documented == {*ACTIONS, "ping"}
    assert len(DOCS) == len(ACTIONS)


def test_operation_ids_match_actions(spec: dict[str, Any]) -> None:
    for path, item in spec["paths"].items():
        (operation,) = item.values()
        assert operation["operationId"] == path.removeprefix("/")


def test_post_only_actions_document_post(spec: dict[str, Any]) -> None:
    methods = {path: next(iter(item)) for path, item in spec["paths"].items()}

    assert {path for path, method in methods.items() if method == "post"} == {
        "/fileUpload",
        "/imageSave",
        "/imageLoad",
    }


def test_nested_parameters_use_bracket_names(spec: dict[str, Any]) -> None:
    parameters = spec["paths"]["/imageCrop"]["get"]["parameters"]
    box = {p["name"]: p for p in parameters if p["name"].startswith("box[")}

    assert sorted(box) == ["box[h]", "box[w]", "box[x]", "box[y]"]
    assert all(p["required"] for p in box.values())
    assert box["box[w]"]["schema"]["type"] == "integer"
    assert "style" not in box["box[w]"]


def test_optional_object_fields_are_optional(spec: dict[str, Any]) -> None:
    parameters = spec["paths"]["/files"]["get"]["parameters"]
    mods = [p for p in parameters if p["name"].startswith("mods[")]

    assert "mods[sortBy]" in [p["name"] for p in mods]
    assert not any(p["required"] for p in mods)


def test_optional_parameters_are_not_nullable(spec: dict[str, Any]) -> None:
    parameters = spec["paths"]["/files"]["get"]["parameters"]
    source = next(p for p in parameters if p["name"] == "source")

    assert source["required"] is False
    assert source["schema"]["type"] == "string"
    assert "default" not in source["schema"]


def test_move_parameter_uses_wire_name(spec: dict[str, Any]) -> None:
    parameters = spec["paths"]["/fileMove"]["get"]["parameters"]

    assert [p["name"] for p in parameters] == ["source", "from", "path"]


def test_binary_answers(spec: dict[str, Any]) -> None:
    pdf = spec["paths"]["/generatePdf"]["get"]["responses"]["200"]

    assert pdf["content"]["application/pdf"]["schema"] == {
        "type": "string",
        "format": "binary",
    }


def test_errors_share_the_envelope(spec: dict[str, Any]) -> None:
    responses = spec["paths"]["/files"]["get"]["responses"]

    assert responses["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_servers_can_be_replaced() -> None:
    servers = [{"url": "https://example.com/connector/"}]

    assert build_openapi(servers)["servers"] == servers
