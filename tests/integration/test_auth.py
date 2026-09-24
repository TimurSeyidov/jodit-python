"""Authentication callback."""

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from jcpy.config.loader import build_config
from jcpy.connector import Connector

if TYPE_CHECKING:
    from starlette.requests import Request

    from jcpy.types import JsonObject
    from tests.conftest import ClientFactory


async def test_default_role_without_callback(
    connector_client: ClientFactory,
) -> None:
    async with connector_client({"defaultRole": "viewer"}) as http:
        response = await http.get("/echo")

    assert response.json()["data"]["role"] == "viewer"


async def test_sync_callback_sets_role(
    connector_client: ClientFactory,
) -> None:
    def auth(request: Request) -> str:
        return "admin" if request.headers.get("x-token") else "guest"

    async with connector_client(check_authentication=auth) as http:
        response = await http.get("/echo", headers={"X-Token": "t"})

    assert response.json()["data"]["role"] == "admin"


async def test_async_callback_sets_role(
    connector_client: ClientFactory,
) -> None:
    async def auth(_: Request) -> str:
        await asyncio.sleep(0)
        return "editor"

    async with connector_client(check_authentication=auth) as http:
        response = await http.get("/echo")

    assert response.json()["data"]["role"] == "editor"


async def test_callback_error_fails_the_request(
    connector_client: ClientFactory,
) -> None:
    def auth(_: Request) -> str:
        msg = "Unauthorized"
        raise PermissionError(msg)

    async with connector_client(check_authentication=auth) as http:
        response = await http.get("/echo")

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "data": {"code": 500, "messages": ["Unauthorized"]},
    }


async def test_async_callback_rejection_fails_the_request(
    connector_client: ClientFactory,
) -> None:
    async def auth(_: Request) -> str:
        msg = "Authentication failed"
        raise PermissionError(msg)

    async with connector_client(check_authentication=auth) as http:
        response = await http.get("/echo")

    assert response.status_code == 500
    assert response.json()["data"]["messages"] == ["Authentication failed"]


async def test_callback_must_return_a_string(
    connector_client: ClientFactory,
) -> None:
    def auth(_: Request) -> str:
        return None  # type: ignore[return-value]

    async with connector_client(check_authentication=auth) as http:
        response = await http.get("/echo")

    assert response.status_code == 500


def test_warns_about_open_access(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="jcpy")

    Connector(build_config({}))

    assert "full access" in caplog.text


@pytest.mark.parametrize(
    "config", [{"accessControl": [{"role": "*", "FILES": True}]}, None]
)
def test_no_warning_when_access_is_configured(
    caplog: pytest.LogCaptureFixture, config: JsonObject | None
) -> None:
    caplog.set_level(logging.WARNING, logger="jcpy")

    def auth(_: Request) -> str:
        return "guest"

    if config is None:
        Connector(build_config({}), check_authentication=auth)
    else:
        Connector(build_config(config))

    assert "full access" not in caplog.text
