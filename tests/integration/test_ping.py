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


async def test_ping_ignores_cors_and_authentication(
    connector_client: ClientFactory,
) -> None:
    def reject(_: object) -> str:
        msg = "never called"
        raise AssertionError(msg)

    async with connector_client(
        {"allowCrossOrigin": True}, check_authentication=reject
    ) as http:
        response = await http.get("/ping", headers={"Origin": "http://a"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
