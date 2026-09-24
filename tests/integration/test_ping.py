"""Liveness probe."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_ping_returns_success(client: AsyncClient) -> None:
    response = await client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"success": True}


async def test_ping_rejects_post(client: AsyncClient) -> None:
    response = await client.post("/ping")

    assert response.status_code == 405
