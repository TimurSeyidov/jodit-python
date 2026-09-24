"""jodit-nodejs tests whose configuration holds functions or adapters.

``make parity`` runs the jodit-nodejs suite against this port, but
callbacks and adapter instances cannot cross the process boundary.
These tests mirror those cases (``custom-svg-generator``,
``custom-storage-adapter``, ``dynamic-sources``,
``async-access-control``) with Python callbacks.
"""

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from jcpy.config.models import AccessControlRule
from jcpy.storage import register_storage_adapter
from jcpy.tenants import ResolvedSources
from jcpy.v1 import ACTIONS
from tests.conftest import make_app, open_client, write_file
from tests.memory_storage import MemoryStorageAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from httpx import AsyncClient
    from starlette.requests import Request

    from jcpy.helpers.svg_icon import SvgGenerator
    from jcpy.storage.base import StatEntry
    from jcpy.types import JsonObject, JsonValue

TEST_BASEURL = "http://localhost:8081/files/test/"


def server_config(root: Path, **settings: JsonValue) -> JsonObject:
    """Mirror ``startTestServer`` of jodit-nodejs."""
    config: JsonObject = {
        "defaultFilesKey": "files",
        "allowPrivateNetworkUploads": True,
        "sources": {
            "test": {
                "name": "test",
                "title": "Test Files",
                "root": str(root),
                "baseurl": TEST_BASEURL,
                "defaultFilesKey": "files",
            }
        },
    }
    config.update(settings)
    (root / "subdir").mkdir(parents=True, exist_ok=True)
    return config


def files_of(body: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    (source,) = body["data"]["sources"]
    files: list[dict[str, Any]] = source["files"]
    return files


# --- custom-svg-generator ------------------------------------------------


async def svg_listing(
    root: Path, generator: SvgGenerator, **settings: JsonValue
) -> Any:  # noqa: ANN401
    app = make_app(
        server_config(root, createThumb=True, **settings),
        svg_generator=generator,
        actions=ACTIONS,
    )
    async with open_client(app) as http:
        response = await http.get(
            "/", params={"action": "files", "source": "test"}
        )
    assert response.status_code == 200
    return response.json()


async def test_custom_svg_generator_is_used(tmp_path: Path) -> None:
    def generator(entry: StatEntry, width: int, height: int) -> str:
        color = "#3498db" if entry.is_directory else "#e74c3c"
        return f'<svg width="{width}" height="{height}" fill="{color}"/>'

    write_file(tmp_path, "document.txt", "test content")

    body = await svg_listing(
        tmp_path, generator, svgThumbWidth=100, svgThumbHeight=100
    )

    (item,) = [f for f in files_of(body) if f["file"] == "document.txt"]
    assert "_thumbs" in str(item["thumb"])
    assert ".svg" in str(item["thumb"])
    icon = (tmp_path / "_thumbs" / "document.txt.svg").read_text()
    assert "#e74c3c" in icon


async def test_custom_svg_generator_parameters(tmp_path: Path) -> None:
    captured: list[tuple[str, int, int]] = []

    def spy(entry: StatEntry, width: int, height: int) -> str:
        captured.append((entry.path, width, height))
        return "<svg><rect/></svg>"

    write_file(tmp_path, "test.txt", "content")

    await svg_listing(tmp_path, spy, svgThumbWidth=150, svgThumbHeight=200)

    assert any(
        path.endswith("test.txt") and (width, height) == (150, 200)
        for path, width, height in captured
    )


async def test_generate_svg_thumbs_off_wins(tmp_path: Path) -> None:
    write_file(tmp_path, "doc.txt", "content")

    body = await svg_listing(
        tmp_path, lambda *_: "<svg/>", generateSvgThumbs=False
    )

    (item,) = [f for f in files_of(body) if f["file"] == "doc.txt"]
    assert "_thumbs" not in str(item.get("thumb", ""))


async def test_svg_generator_errors_fail_the_listing(
    tmp_path: Path,
) -> None:
    def broken(*_: object) -> str:
        msg = "Generator failed"
        raise RuntimeError(msg)

    write_file(tmp_path, "test.txt", "content")
    app = make_app(
        server_config(tmp_path, createThumb=True),
        svg_generator=broken,
        actions=ACTIONS,
    )

    async with open_client(app) as http:
        response = await http.get(
            "/", params={"action": "files", "source": "test"}
        )

    # jodit-nodejs does not catch generator errors either.
    assert response.status_code == 500
    assert response.json()["data"]["messages"] == ["Generator failed"]


async def test_custom_svg_generator_for_folders(tmp_path: Path) -> None:
    def generator(entry: StatEntry, width: int, height: int) -> str:
        color = "#2ecc71" if entry.is_directory else "#95a5a6"
        return f'<svg width="{width}" height="{height}" fill="{color}"/>'

    app = make_app(
        server_config(
            tmp_path, createThumb=True, safeThumbsCountInOneTime=100
        ),
        svg_generator=generator,
        actions=ACTIONS,
    )
    async with open_client(app) as http:
        response = await http.get(
            "/",
            params={
                "action": "files",
                "source": "test",
                "mods[withFolders]": "true",
            },
        )

    folders = [f for f in files_of(response.json()) if f["type"] == "folder"]
    assert [f["file"] for f in folders] == ["subdir"]
    assert str(folders[0]["thumb"]).endswith(".svg")
    icon = (tmp_path / "_thumbs" / "subdir.svg").read_text()
    assert "#2ecc71" in icon


# --- custom-storage-adapter ---------------------------------------------


@pytest.fixture
async def memory_client(
    tmp_path: Path,
) -> AsyncIterator[tuple[MemoryStorageAdapter, AsyncClient]]:
    adapter = MemoryStorageAdapter()
    await adapter.write("test.txt", b"Hello World")
    await adapter.write("image.png", b"fake png")
    await adapter.write("subdir/nested.txt", b"Nested file")
    register_storage_adapter("parity-memory", lambda _: adapter)
    config = server_config(
        tmp_path,
        sources={
            "memory": {
                "name": "memory",
                "title": "In-Memory Storage",
                "root": str(tmp_path),
                "baseurl": "http://localhost:8081/files/memory/",
                "storageAdapter": "parity-memory",
            }
        },
    )
    async with open_client(make_app(config, actions=ACTIONS)) as http:
        yield adapter, http


async def test_memory_adapter_actions(
    memory_client: tuple[MemoryStorageAdapter, AsyncClient],
) -> None:
    adapter, http = memory_client
    await adapter.create_directory("todelete")
    await adapter.write("toremove.txt", b"delete me")
    await adapter.write("old-name.txt", b"rename test")

    listing = await http.get(
        "/",
        params={
            "action": "files",
            "source": "memory",
            "mods[withFolders]": "true",
        },
    )
    nested = await http.get(
        "/",
        params={"action": "files", "source": "memory", "path": "/subdir"},
    )
    folders = await http.get(
        "/", params={"action": "folders", "source": "memory"}
    )
    created = await http.post(
        "/",
        data={
            "action": "folderCreate",
            "source": "memory",
            "name": "newfolder",
        },
    )
    removed_folder = await http.post(
        "/",
        data={
            "action": "folderRemove",
            "source": "memory",
            "name": "todelete",
        },
    )
    uploaded = await http.post(
        "/",
        data={"action": "fileUpload", "source": "memory"},
        files={"files": ("uploaded.txt", b"uploaded content")},
    )
    downloaded = await http.get(
        "/",
        params={
            "action": "fileDownload",
            "source": "memory",
            "name": "test.txt",
        },
    )
    removed_file = await http.post(
        "/",
        data={
            "action": "fileRemove",
            "source": "memory",
            "name": "toremove.txt",
        },
    )
    renamed = await http.post(
        "/",
        data={
            "action": "fileRename",
            "source": "memory",
            "name": "old-name.txt",
            "newname": "new-name.txt",
        },
    )

    names = [item["name"] for item in files_of(listing.json())]
    assert {"test.txt", "image.png", "subdir"} <= set(names)
    assert "nested.txt" in [item["name"] for item in files_of(nested.json())]
    assert "subdir" in folders.json()["data"]["sources"][0]["folders"]
    for response in (created, removed_folder, uploaded, removed_file, renamed):
        assert response.status_code == 200, response.text
    assert await adapter.directory_exists("newfolder")
    assert not await adapter.directory_exists("todelete")
    assert await adapter.read("uploaded.txt") == b"uploaded content"
    assert downloaded.content == b"Hello World"
    assert not await adapter.file_exists("toremove.txt")
    assert not await adapter.file_exists("old-name.txt")
    assert await adapter.file_exists("new-name.txt")


# --- dynamic-sources ----------------------------------------------------


async def test_dynamic_sources(tmp_path: Path) -> None:
    tenant_a = MemoryStorageAdapter()
    tenant_b = MemoryStorageAdapter()
    await tenant_a.write("a.txt", b"tenant a")
    await tenant_b.write("b.txt", b"tenant b")
    register_storage_adapter("parity-tenant-a", lambda _: tenant_a)
    register_storage_adapter("parity-tenant-b", lambda _: tenant_b)
    resolver_calls: list[str] = []
    seen_tenant: list[str | None] = []

    def tenant_source(name: str) -> dict[str, dict[str, str]]:
        return {
            "files": {
                "name": "files",
                "title": f"Tenant {name}",
                "baseurl": f"http://cdn.example.com/{name}/",
                "storageAdapter": f"parity-tenant-{name}",
            }
        }

    def resolve(request: Request) -> ResolvedSources | None:
        tenant = request.headers.get("x-tenant")
        resolver_calls.append(tenant or "")
        if tenant in {"a", "b"}:
            return ResolvedSources(
                id=f"tenant-{tenant}", sources=tenant_source(tenant)
            )
        return None

    def role(request: Request) -> str:
        seen_tenant.append(request.headers.get("x-tenant"))
        return "reader" if request.headers.get("x-tenant") == "b" else "guest"

    app = make_app(
        server_config(tmp_path),
        resolve_sources=resolve,
        check_authentication=role,
        actions=ACTIONS,
    )

    async with open_client(app) as http:

        async def names(tenant: str | None) -> list[str]:
            response = await http.get(
                "/",
                params={
                    "action": "files",
                    "source": "test" if tenant is None else "files",
                },
                headers={} if tenant is None else {"x-tenant": tenant},
            )
            assert response.status_code == 200
            return [str(item["name"]) for item in files_of(response.json())]

        ping = await http.get("/ping")
        assert ping.status_code == 200
        assert resolver_calls == []

        assert await names("a") == ["a.txt"]
        assert await names("b") == ["b.txt"]

        tenant_b_listing = await http.get(
            "/",
            params={"action": "files", "source": "files"},
            headers={"x-tenant": "b"},
        )
        assert (
            tenant_b_listing.json()["data"]["sources"][0]["baseurl"]
            == "http://cdn.example.com/b/"
        )

        upload = await http.post(
            "/",
            data={"action": "fileUpload", "source": "files"},
            files={"files": ("upload.txt", b"from a")},
            headers={"x-tenant": "a"},
        )
        assert upload.status_code == 200
        assert await tenant_a.file_exists("upload.txt")
        assert not await tenant_b.file_exists("upload.txt")

        fallback = await http.get("/", params={"action": "files"})
        assert fallback.json()["data"]["sources"][0]["name"] == "test"

        hidden = await http.get(
            "/", params={"action": "files", "source": "files"}
        )
        assert hidden.status_code == 404

        before = len(resolver_calls)
        await names("a")
        await names("a")
        assert len(resolver_calls) == before + 2
        assert {"a.txt", "upload.txt"} <= set(await names("a"))

        await names("b")
        assert seen_tenant[-1] == "b"


# --- async-access-control -----------------------------------------------


@pytest.mark.parametrize(("allowed", "status"), [(False, 403), (True, 200)])
async def test_access_control_function(
    tmp_path: Path, allowed: bool, status: int
) -> None:
    async def load_rules() -> list[AccessControlRule]:
        await asyncio.sleep(0.01)
        return [
            AccessControlRule.model_validate(
                {"role": "guest", "FILES": allowed}
            )
        ]

    write_file(tmp_path, "test.txt", "content")
    app = make_app(
        server_config(tmp_path, defaultRole="guest"),
        access_control=load_rules,
        actions=ACTIONS,
    )

    async with open_client(app) as http:
        response = await http.get(
            "/", params={"action": "files", "source": "test"}
        )

    assert response.status_code == status
    if not allowed:
        assert response.json()["data"]["messages"] == ["Access denied"]
