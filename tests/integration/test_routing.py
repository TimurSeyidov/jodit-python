"""Routing, parameter collection and error envelopes."""

import logging
from typing import TYPE_CHECKING

import pytest

from jcpy.context import BODY_LIMIT

if TYPE_CHECKING:
    from tests.conftest import ClientFactory


async def test_action_from_query(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.get(
            "/", params={"action": "echo", "source": "test"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "code": 220,
            "role": "guest",
            "action": "echo",
            "params": {"action": "echo", "source": "test"},
            "files": [],
        },
    }


async def test_action_from_path_matches_query_form(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        by_query = await http.get("/?action=echo&x=1")
        by_path = await http.get("/echo?x=1")

    assert by_path.status_code == 200
    assert by_path.json() == by_query.json()


async def test_path_action_wins_over_query_and_body(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo?action=fail", json={"action": "fail"}
        )

    assert response.json()["data"]["action"] == "echo"


async def test_query_wins_over_body(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/?action=echo&path=/q", json={"path": "/b", "source": "s"}
        )

    params = response.json()["data"]["params"]
    assert params == {"action": "echo", "path": "/q", "source": "s"}


async def test_nested_objects_are_merged(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo?mods[offset]=10&tags[]=q",
            json={"mods": {"sortBy": "name"}, "tags": ["b"]},
        )

    params = response.json()["data"]["params"]
    assert params["mods"] == {"sortBy": "name", "offset": "10"}
    assert params["tags"] == ["b", "q"]


async def test_bracket_query_parameters(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.get(
            "/echo?options[format]=A4&options[margin][top]=10"
        )

    assert response.json()["data"]["params"]["options"] == {
        "format": "A4",
        "margin": {"top": "10"},
    }


async def test_urlencoded_body(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/",
            content="action=echo&mods[withFolders]=true",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.json()["data"]["params"] == {
        "action": "echo",
        "mods": {"withFolders": "true"},
    }


async def test_multipart_fields_and_files(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo",
            data={"source": "test", "mods[offset]": "5"},
            files=[
                ("files[0]", ("a.txt", b"a", "text/plain")),
                ("files[1]", ("b.txt", b"b", "text/plain")),
            ],
        )

    data = response.json()["data"]
    assert data["params"] == {
        "source": "test",
        "mods": {"offset": "5"},
        "action": "echo",
    }
    assert data["files"] == ["a.txt", "b.txt"]


async def test_json_body_on_get_is_read(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.request(
            "GET", "/", json={"action": "echo", "path": "/x"}
        )

    assert response.json()["data"]["params"]["path"] == "/x"


async def test_json_array_body_is_ignored(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post("/echo", json=[1, 2])

    assert response.json()["data"]["params"] == {"action": "echo"}


async def test_empty_json_body(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo", headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 200


async def test_unsupported_body_type_is_ignored(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo?x=1",
            content="plain",
            headers={"Content-Type": "text/plain"},
        )

    assert response.json()["data"]["params"] == {"x": "1", "action": "echo"}


@pytest.mark.parametrize("body", ["{broken", '"text"'])
async def test_invalid_json_body(
    connector_client: ClientFactory, body: str
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json()["data"]["messages"][0].startswith(
        "Invalid JSON body"
    )


async def test_body_over_limit(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo",
            content="a=" + "x" * BODY_LIMIT,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 413


async def test_too_many_urlencoded_parameters(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo",
            content="&".join(f"k{index}=1" for index in range(1001)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 413
    assert response.json()["data"]["messages"] == ["too many parameters"]


async def test_urlencoded_depth_limit(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/echo",
            content="a" + "[b]" * 40 + "=1",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 400
    assert response.json()["data"]["messages"] == [
        "The input exceeded the depth"
    ]


@pytest.mark.parametrize("url", ["/?action=nope", "/nope"])
async def test_unknown_action(
    connector_client: ClientFactory, url: str
) -> None:
    async with connector_client() as http:
        response = await http.get(url)

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "data": {"code": 404, "messages": ['Action "nope" not found']},
    }


async def test_missing_action_is_default(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.get("/")

    assert response.json()["data"]["messages"] == [
        'Action "default" not found'
    ]


async def test_numeric_action_keeps_its_text(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post("/", json={"action": 12})

    assert response.json()["data"]["messages"] == ['Action "12" not found']


async def test_http_error_from_handler(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.get("/fail?kind=http")

    assert response.status_code == 403
    assert response.json() == {
        "success": False,
        "data": {"code": 403, "messages": ["Access denied"]},
    }


async def test_unexpected_error_from_handler(
    connector_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    async with connector_client() as http:
        response = await http.get("/fail")

    assert response.status_code == 500
    assert response.json()["data"] == {"code": 500, "messages": ["Boom"]}
    assert "Request failed" in caplog.text


async def test_errors_are_not_logged_without_debug(
    connector_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR, logger="jcpy")
    async with connector_client({"debug": False}) as http:
        await http.get("/fail")

    assert "Request failed" not in caplog.text


async def test_options_without_cors_lists_methods(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.options("/")

    assert response.status_code == 200
    assert response.headers["allow"] == "GET, HEAD, POST"


async def test_uploaded_files_are_closed_after_the_answer(
    connector_client: ClientFactory,
) -> None:
    async with connector_client(
        {"accessControl": [{"FILE_UPLOAD": False}]}
    ) as http:
        denied = await http.post(
            "/fileUpload", files={"files[0]": ("a.txt", b"a")}
        )
        echoed = await http.post("/echo", files={"files[0]": ("a.txt", b"a")})

    # A leaked temporary file would fail the test (ResourceWarning).
    assert denied.status_code == 403
    assert echoed.json()["data"]["files"] == ["a.txt"]
