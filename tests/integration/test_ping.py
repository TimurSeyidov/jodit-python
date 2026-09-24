"""Liveness probe."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient

    from tests.conftest import ClientFactory


async def test_ping_returns_success(client: AsyncClient) -> None:
    response = await client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"success": True}


async def test_post_ping_is_an_unknown_action(client: AsyncClient) -> None:
    response = await client.post("/ping")

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "data": {"code": 404, "messages": ['Action "ping" not found']},
    }


async def test_ping_is_blocked_in_only_post_mode(
    connector_client: ClientFactory,
) -> None:
    async with connector_client({"onlyPOST": True}) as http:
        response = await http.get("/ping")

    assert response.status_code == 405
    assert response.json()["data"]["messages"] == [
        "GET requests are disabled. Use POST instead."
    ]


async def test_ping_needs_no_authentication(
    connector_client: ClientFactory,
) -> None:
    def reject(_: object) -> str:
        msg = "never called"
        raise AssertionError(msg)

    async with connector_client(
        {"allowCrossOrigin": True, "allowedOrigins": ["http://a"]},
        check_authentication=reject,
    ) as http:
        allowed = await http.get("/ping", headers={"Origin": "http://a"})
        other = await http.get("/ping", headers={"Origin": "http://b"})
        plain = await http.get("/ping")

    assert allowed.status_code == other.status_code == plain.status_code
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://a"
    assert "access-control-allow-origin" not in other.headers


async def test_ping_without_cross_origin_has_no_cors_headers(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.get("/ping", headers={"Origin": "http://a"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
