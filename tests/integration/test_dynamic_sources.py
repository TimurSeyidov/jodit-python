"""Multi-tenant sources, ported from jodit-nodejs dynamic-sources.test.ts."""

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse

from jcpy.acl import AccessControl
from jcpy.config.loader import build_config
from jcpy.connector import Connector
from jcpy.tenants import ResolvedSources
from tests.conftest import make_app, open_client, source_config, write_file

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from starlette.requests import Request
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.sources import SourcePool
    from jcpy.types import JsonValue


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    paths = {name: tmp_path / name for name in ("static", "a", "b")}
    write_file(paths["static"], "static.txt", "static")
    write_file(paths["a"], "a.txt", "tenant a")
    write_file(paths["b"], "b.txt", "tenant b")
    return paths


class Tenants:
    """Resolver keyed by the ``X-Tenant`` header."""

    def __init__(self, roots: dict[str, Path]) -> None:
        self.roots = roots
        self.calls: list[str] = []

    async def __call__(self, request: Request) -> ResolvedSources | None:
        name = request.headers.get("x-tenant", "")
        self.calls.append(name)
        if name not in {"a", "b"}:
            return None
        return ResolvedSources(
            f"tenant-{name}",
            {
                "files": {
                    "title": f"Tenant {name}",
                    "root": str(self.roots[name]),
                    "baseurl": f"http://cdn.example.com/{name}/",
                }
            },
        )


def role(request: Request) -> str:
    return "reader" if request.headers.get("x-tenant") == "b" else "guest"


async def names(http: AsyncClient, tenant: str | None = None) -> list[str]:
    headers = {"X-Tenant": tenant} if tenant else {}
    response = await http.get(
        "/files",
        params={"source": "test" if tenant is None else "files"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return [
        item["name"] for item in response.json()["data"]["sources"][0]["files"]
    ]


async def test_each_tenant_gets_its_own_storage(
    roots: dict[str, Path],
) -> None:
    resolver = Tenants(roots)
    app = make_app(
        source_config(roots["static"], createThumb=False),
        resolve_sources=resolver,
        check_authentication=role,
    )
    async with open_client(app) as http:
        assert await names(http, "a") == ["a.txt"]
        assert await names(http, "b") == ["b.txt"]
        assert await names(http) == ["static.txt"]
        response = await http.get(
            "/files", params={"source": "files"}, headers={"X-Tenant": "a"}
        )

    assert response.json()["data"]["sources"][0]["baseurl"] == (
        "http://cdn.example.com/a/"
    )
    assert resolver.calls == ["a", "b", "", "a"]


async def test_writes_land_in_the_right_tenant(roots: dict[str, Path]) -> None:
    app = make_app(
        source_config(roots["static"], createThumb=False),
        resolve_sources=Tenants(roots),
    )
    async with open_client(app) as http:
        response = await http.post(
            "/folderCreate",
            json={"source": "files", "name": "new"},
            headers={"X-Tenant": "a"},
        )

    assert response.status_code == 200
    assert (roots["a"] / "new").is_dir()
    assert not (roots["b"] / "new").exists()


async def test_tenant_sources_are_hidden_without_the_header(
    roots: dict[str, Path],
) -> None:
    app = make_app(
        source_config(roots["static"]), resolve_sources=Tenants(roots)
    )
    async with open_client(app) as http:
        response = await http.get("/files", params={"source": "files"})

    assert response.status_code == 404
    assert response.json()["data"]["messages"] == ["Source not found"]


async def test_sources_are_built_once_per_id(roots: dict[str, Path]) -> None:
    pools: list[SourcePool] = []

    async def spy(context: ActionContext) -> Response:
        pools.append(context.sources)
        return JSONResponse({})

    connector = Connector(
        build_config(source_config(roots["static"])),
        resolve_sources=Tenants(roots),
        actions={"spy": spy},
    )
    app = FastAPI()
    app.include_router(connector.build_router())
    async with open_client(app) as http:
        for _ in range(2):
            await http.get("/spy", headers={"X-Tenant": "a"})
        connector.clear_dynamic_sources()
        await http.get("/spy", headers={"X-Tenant": "a"})

    assert pools[0] is pools[1]
    assert pools[2] is not pools[0]


async def test_resolver_runs_before_authentication(
    roots: dict[str, Path],
) -> None:
    order: list[str] = []

    def resolver(request: Request) -> ResolvedSources | None:
        order.append("resolve")
        return None

    def auth(request: Request) -> str:
        order.append("auth")
        return "guest"

    app = make_app(
        source_config(roots["static"]),
        resolve_sources=resolver,
        check_authentication=auth,
    )
    async with open_client(app) as http:
        await http.get("/files")
        await http.get("/ping")

    assert order == ["resolve", "auth"]


async def test_only_tenant_sources_configured(roots: dict[str, Path]) -> None:
    rules: JsonValue = [{"role": "*", "FILES": True}]
    app = make_app(
        {"sources": {}, "accessControl": rules},
        resolve_sources=Tenants(roots),
        access_control_instance=AccessControl([]),
    )
    async with open_client(app) as http:
        tenant = await http.get("/files", headers={"X-Tenant": "b"})
        none = await http.get("/files")

    assert tenant.status_code == 200
    assert none.json()["data"]["sources"] == []
