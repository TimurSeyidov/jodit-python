"""``onlyPOST`` mode."""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.conftest import ClientFactory

MESSAGE = "GET requests are disabled. Use POST instead."


@pytest.mark.parametrize("url", ["/?action=echo", "/echo"])
async def test_get_is_allowed_by_default(
    connector_client: ClientFactory, url: str
) -> None:
    async with connector_client() as http:
        response = await http.get(url)

    assert response.status_code == 200


@pytest.mark.parametrize("url", ["/?action=echo", "/echo"])
async def test_get_is_blocked(
    connector_client: ClientFactory, url: str
) -> None:
    async with connector_client({"onlyPOST": True}) as http:
        response = await http.get(url)

    assert response.status_code == 405
    assert response.json() == {
        "success": False,
        "data": {"code": 405, "messages": [MESSAGE]},
    }


async def test_get_is_blocked_before_authentication(
    connector_client: ClientFactory,
) -> None:
    calls: list[str] = []

    def auth(_: object) -> str:
        calls.append("auth")
        return "admin"

    async with connector_client(
        {"onlyPOST": True}, check_authentication=auth
    ) as http:
        await http.get("/echo")

    assert calls == []


@pytest.mark.parametrize("url", ["/", "/echo"])
async def test_post_is_allowed(
    connector_client: ClientFactory, url: str
) -> None:
    async with connector_client({"onlyPOST": True}) as http:
        response = await http.post(url, json={"action": "echo"})

    assert response.status_code == 200
    assert response.json()["success"] is True
