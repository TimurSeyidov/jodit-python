"""``permissions`` action and source selection."""

import logging
from typing import TYPE_CHECKING

import pytest

from jcpy.storage import register_storage_adapter
from tests.conftest import make_app, open_client
from tests.memory_storage import MemoryStorageAdapter

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient

    from jcpy.types import JsonObject, JsonValue
    from tests.conftest import ClientFactory

ALL_ALLOWED = {
    "allowFiles": True,
    "allowFileMove": True,
    "allowFileCopy": True,
    "allowFileUpload": True,
    "allowFileUploadRemote": True,
    "allowFileRemove": True,
    "allowFileRename": True,
    "allowFileDownload": True,
    "allowFolders": True,
    "allowFolderMove": True,
    "allowFolderCopy": True,
    "allowFolderCreate": True,
    "allowFolderRemove": True,
    "allowFolderRename": True,
    "allowFolderTree": True,
    "allowImageResize": True,
    "allowImageCrop": True,
    "allowImageSave": True,
    "allowImageLoad": True,
    "allowGeneratePdf": True,
    "allowGenerateDocx": True,
}


def config(tmp_path: Path, **extra: JsonValue) -> JsonObject:
    return {
        "sources": {
            "test": {
                "title": "Test Files",
                "root": str(tmp_path),
                "baseurl": "http://localhost:8081/files/test/",
            }
        },
        **extra,
    }


async def permissions(http: AsyncClient, **params: str) -> JsonObject:
    response = await http.get(
        "/", params={"action": "permissions", "source": "test", **params}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["code"] == 220
    result: JsonObject = data["permissions"]
    return result


async def test_all_allowed_by_default(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    async with connector_client(config(tmp_path)) as http:
        assert await permissions(http) == ALL_ALLOWED
        assert list(await permissions(http)) == list(ALL_ALLOWED)


async def test_post_and_path_alias(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    async with connector_client(config(tmp_path)) as http:
        response = await http.post(
            "/permissions", json={"source": "test", "path": "/subfolder"}
        )

    assert response.json()["data"]["permissions"] == ALL_ALLOWED


@pytest.mark.parametrize("method", ["get", "post"])
async def test_unknown_source(
    connector_client: ClientFactory, tmp_path: Path, method: str
) -> None:
    body = {"action": "permissions", "source": "non-existent-source"}
    async with connector_client(config(tmp_path)) as http:
        if method == "get":
            response = await http.get("/", params=body)
        else:
            response = await http.post("/", json=body)

    assert response.status_code == 404
    assert response.json()["data"]["messages"] == ["Source not found"]


async def test_rules_are_reflected(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    rules: JsonValue = [
        {"role": "guest", "FILE_UPLOAD": False, "FILE_REMOVE": False},
        {"role": "admin", "FOLDERS": False},
    ]
    async with connector_client(
        config(tmp_path, accessControl=rules, defaultRole="guest")
    ) as http:
        result = await permissions(http)

    assert result["allowFileUpload"] is False
    assert result["allowFileRemove"] is False
    assert result["allowFolders"] is True
    assert result["allowFiles"] is True


async def test_path_rules_see_absolute_paths(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    rules: JsonValue = [{"path": str(tmp_path / "private"), "FILES": False}]
    async with connector_client(config(tmp_path, accessControl=rules)) as http:
        public = await permissions(http, path="/public")
        private = await permissions(http, path="/private/docs")

    assert public["allowFiles"] is True
    assert private["allowFiles"] is False


async def test_invalid_path_denies_everything(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    async with connector_client(config(tmp_path)) as http:
        result = await permissions(http, path="../../etc")

    assert set(result.values()) == {False}


async def test_without_sources_denies_everything(
    connector_client: ClientFactory,
) -> None:
    async with connector_client({"sources": {}}) as http:
        response = await http.get("/permissions")

    assert set(response.json()["data"]["permissions"].values()) == {False}


async def test_first_source_is_used_without_name(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    rules: JsonValue = [{"path": str(tmp_path / "b"), "FILES": False}]
    sources = {
        "b": {
            "title": "B",
            "root": str(tmp_path / "b"),
            "baseurl": "http://b/",
        },
        "a": {
            "title": "A",
            "root": str(tmp_path / "a"),
            "baseurl": "http://a/",
        },
    }
    async with connector_client(
        {"sources": sources, "accessControl": rules}
    ) as http:
        response = await http.get("/permissions")

    assert response.json()["data"]["permissions"]["allowFiles"] is False


async def test_denied_source_root_is_logged(
    connector_client: ClientFactory,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="jcpy")
    rules: JsonValue = [{"path": str(tmp_path), "PERMISSIONS": False}]
    async with connector_client(config(tmp_path, accessControl=rules)) as http:
        response = await http.get(
            "/permissions", params={"source": "test", "path": "/x"}
        )

    assert response.status_code == 200
    assert "Access denied for source test action permissions" in caplog.text


async def test_unknown_storage_adapter_fails_requests(
    connector_client: ClientFactory,
) -> None:
    sources = {
        "s": {"title": "S", "baseurl": "http://s/", "storageAdapter": "nope"}
    }
    async with connector_client({"sources": sources}) as http:
        response = await http.get("/permissions")

    assert response.status_code == 400
    assert response.json()["data"]["messages"][0].startswith(
        'Unknown storage adapter "nope"'
    )


async def test_remote_source_uses_virtual_root() -> None:
    register_storage_adapter("memory", lambda _: MemoryStorageAdapter())
    rules: JsonValue = [{"path": "/media/private", "FILES": False}]
    sources: JsonObject = {
        "m": {
            "title": "M",
            "baseurl": "http://m/",
            "storageAdapter": "memory",
            "root": "/media",
        },
        "v": {
            "title": "V",
            "baseurl": "http://v/",
            "storageAdapter": "memory",
        },
    }
    app = make_app({"sources": sources, "accessControl": rules})
    async with open_client(app) as http:
        private = await http.get(
            "/permissions", params={"source": "m", "path": "private"}
        )
        virtual = await http.get("/permissions", params={"source": "v"})

    assert private.json()["data"]["permissions"]["allowFiles"] is False
    assert virtual.json()["data"]["permissions"] == ALL_ALLOWED
