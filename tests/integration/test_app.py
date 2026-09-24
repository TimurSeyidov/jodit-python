"""Application factories, embedding and instance isolation."""

import asyncio
import json
from importlib.metadata import version
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse

from jcpy import create_app, create_router
from jcpy.app import _VersionHeaderMiddleware
from jcpy.errors import ConfigError
from tests.conftest import make_app, open_client

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import Message, Receive, Scope, Send

    from jcpy.context import ActionContext


async def test_create_app_adds_version_header() -> None:
    async with open_client(create_app()) as http:
        response = await http.get("/ping")

    assert response.headers["x-app-version"] == version("jodit-python")


async def test_create_app_reads_config_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"onlyPOST": True}))

    async with open_client(create_app(path)) as http:
        response = await http.get("/")

    assert response.status_code == 405


async def test_create_app_reads_config_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONFIG", json.dumps({"onlyPOST": True}))

    async with open_client(create_app()) as http:
        response = await http.get("/")

    assert response.status_code == 405


def test_invalid_config_fails_at_startup(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"onlyPost": True}))

    with pytest.raises(ConfigError, match="onlyPost"):
        create_app(path)


async def test_router_in_existing_app_keeps_its_routes(
    tmp_path: Path,
) -> None:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(create_router(), prefix="/jodit")

    async with open_client(app) as http:
        health_response = await http.get("/health")
        ping = await http.get("/jodit/ping")
        unknown = await http.get("/jodit/?action=nope")

    assert health_response.json() == {"status": "ok"}
    assert ping.json() == {"success": True}
    assert unknown.status_code == 404
    assert "x-app-version" not in ping.headers


async def test_router_passes_callbacks(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"allowCrossOrigin": True}))
    app = FastAPI()
    app.include_router(
        create_router(
            path,
            check_authentication=lambda _: "admin",
            allowed_origins=lambda origin, _: origin == "http://ok",
        )
    )

    async with open_client(app) as http:
        allowed = await http.get("/nope", headers={"Origin": "http://ok"})
        denied = await http.get("/nope", headers={"Origin": "http://no"})

    assert allowed.headers["access-control-allow-origin"] == "http://ok"
    assert "access-control-allow-origin" not in denied.headers


async def _slow_echo(context: ActionContext) -> Response:
    await asyncio.sleep(0.01)
    return JSONResponse(
        {
            "role": context.role,
            "title": context.config.title,
            "onlyPOST": context.config.only_post,
        }
    )


async def test_instances_are_isolated_under_concurrency() -> None:
    def public_auth(_: Request) -> str:
        return "guest"

    async def admin_auth(_: Request) -> str:
        await asyncio.sleep(0)
        return "admin"

    public = make_app(
        {"title": "public"},
        check_authentication=public_auth,
        actions={"who": _slow_echo},
    )
    admin = make_app(
        {"title": "admin", "onlyPOST": True},
        check_authentication=admin_auth,
        actions={"who": _slow_echo},
    )
    app = FastAPI()
    app.mount("/public", public)
    app.mount("/admin", admin)

    async with open_client(app) as http:
        responses = await asyncio.gather(
            *(
                http.post(f"/{name}/who")
                for _ in range(20)
                for name in ("public", "admin")
            )
        )

    bodies = [response.json() for response in responses]
    assert (
        bodies[0::2]
        == [{"role": "guest", "title": "public", "onlyPOST": False}] * 20
    )
    assert (
        bodies[1::2]
        == [{"role": "admin", "title": "admin", "onlyPOST": True}] * 20
    )


async def test_version_middleware_passes_other_scopes() -> None:
    received: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        received.append(scope["type"])

    middleware = _VersionHeaderMiddleware(inner)

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        return None

    await middleware({"type": "lifespan"}, receive, send)

    assert received == ["lifespan"]
