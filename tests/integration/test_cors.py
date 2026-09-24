"""CORS handling."""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from starlette.requests import Request

    from tests.conftest import ClientFactory

ORIGIN = "https://editor.example"
CORS = {"allowCrossOrigin": True}


async def test_disabled_by_default(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.get("/echo", headers={"Origin": ORIGIN})

    assert "access-control-allow-origin" not in response.headers


async def test_echoes_the_origin(connector_client: ClientFactory) -> None:
    async with connector_client(CORS) as http:
        response = await http.get("/echo", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-headers"] == (
        "Origin,X-Requested-With,Content-Type,Accept,Authorization"
    )
    assert response.headers["access-control-max-age"] == "86400"


async def test_wildcard_without_origin(
    connector_client: ClientFactory,
) -> None:
    async with connector_client(CORS) as http:
        response = await http.get("/echo")

    assert response.headers["access-control-allow-origin"] == "*"


async def test_preflight(connector_client: ClientFactory) -> None:
    async with connector_client(CORS) as http:
        response = await http.options("/echo", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers["access-control-allow-methods"] == (
        "GET, POST, OPTIONS"
    )


async def test_error_responses_carry_cors_headers(
    connector_client: ClientFactory,
) -> None:
    async with connector_client(CORS) as http:
        response = await http.get("/nope", headers={"Origin": ORIGIN})

    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == ORIGIN


@pytest.mark.parametrize(
    ("origin", "allowed"), [(ORIGIN, True), ("https://evil.example", False)]
)
async def test_allowed_origins_list(
    connector_client: ClientFactory, origin: str, allowed: bool
) -> None:
    config = {**CORS, "allowedOrigins": [ORIGIN]}
    async with connector_client(config) as http:
        response = await http.get("/echo", headers={"Origin": origin})

    assert response.status_code == 200
    assert ("access-control-allow-origin" in response.headers) is allowed


async def test_rejected_preflight(connector_client: ClientFactory) -> None:
    config = {**CORS, "allowedOrigins": [ORIGIN]}
    async with connector_client(config) as http:
        response = await http.options(
            "/echo", headers={"Origin": "https://evil.example"}
        )

    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


async def test_sync_origin_predicate(connector_client: ClientFactory) -> None:
    def predicate(origin: str, _: Request) -> bool:
        return origin.endswith(".example")

    async with connector_client(CORS, allowed_origins=predicate) as http:
        good = await http.get("/echo", headers={"Origin": ORIGIN})
        bad = await http.get("/echo", headers={"Origin": "https://x.test"})

    assert good.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in bad.headers


async def test_async_predicate_overrides_list(
    connector_client: ClientFactory,
) -> None:
    async def predicate(origin: str, request: Request) -> bool:
        return request.headers.get("x-tenant") == "yes"

    config = {**CORS, "allowedOrigins": [ORIGIN]}
    async with connector_client(config, allowed_origins=predicate) as http:
        response = await http.get(
            "/echo", headers={"Origin": ORIGIN, "X-Tenant": "no"}
        )

    assert "access-control-allow-origin" not in response.headers
