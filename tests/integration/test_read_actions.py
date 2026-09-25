"""``folders``, ``fileDownload`` and ``getLocalFileByUrl`` actions."""

from typing import TYPE_CHECKING

import pytest

from jcpy.config.loader import build_config
from jcpy.services import resolve_url
from jcpy.services.resolve_url import resolve_file_by_url
from jcpy.sources import SourcePool
from jcpy.storage import register_storage_adapter
from jcpy.storage.base import FileWasNotFoundError, StatEntry
from jcpy.storage.local import LocalStorageAdapter
from jcpy.v1.get_local_file_by_url import handler
from tests.conftest import (
    BASEURL,
    make_app,
    open_client,
    source_config,
    write_file,
)
from tests.memory_storage import MemoryStorageAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from httpx import AsyncClient, Response

    from jcpy.services.resolve_url import ResolvedFile
    from jcpy.sources import Source
    from jcpy.types import JsonObject, JsonValue
    from tests.conftest import ClientFactory


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "test"
    write_file(base, "file1.txt", "one")
    write_file(base, "folder1/child/deep.txt", "deep")
    write_file(base, "folder2/_thumbs/t.svg", "<svg/>")
    write_file(base, "subdir/sub.txt", "sub content")
    write_file(base, "image.png", b"\x89PNG")
    (base / "empty").mkdir()
    (base / ".quarantine").mkdir()
    return base


async def folders(http: AsyncClient, **params: str) -> Response:
    return await http.get(
        "/", params={"action": "folders", "source": "test", **params}
    )


def folder_list(response: Response) -> list[JsonValue]:
    assert response.status_code == 200, response.text
    source: JsonObject = response.json()["data"]["sources"][0]
    result = source["folders"]
    assert isinstance(result, list)
    return result


class TestFolders:
    async def test_root(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await folders(http)

        body = response.json()
        assert list(body["data"]) == ["sources", "code"]
        assert body["data"]["code"] == 220
        source = body["data"]["sources"][0]
        assert source["name"] == "test"
        assert source["title"] == "Test Files"
        assert source["baseurl"] == BASEURL
        assert source["path"] == "/"
        assert source["folders"][0] == "."
        assert sorted(source["folders"][1:]) == [
            "empty",
            "folder1",
            "folder2",
            "subdir",
        ]

    async def test_nested(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await folders(http, path="folder1")

        assert folder_list(response) == ["..", "child"]
        assert response.json()["data"]["sources"][0]["path"] == "folder1"

    async def test_thumbs_folder_is_hidden(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await folders(http, path="folder2")

        assert folder_list(response) == [".."]

    async def test_thumbs_folder_shown_without_thumbnails(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(
            source_config(root, createThumb=False)
        ) as http:
            response = await folders(http, path="folder2")

        assert folder_list(response) == ["..", "_thumbs"]

    @pytest.mark.parametrize("dots", ["false", "true"])
    async def test_dots_parameter(
        self, connector_client: ClientFactory, root: Path, dots: str
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await folders(http, path="folder1", dots=dots)

        assert ("..." in "".join(map(str, folder_list(response)))) is False
        assert (".." in folder_list(response)) is (dots == "true")

    @pytest.mark.parametrize(
        ("params", "status"),
        [
            ({"path": "/non-existent"}, 404),
            ({"source": "nope"}, 404),
            ({"path": "../test-evil"}, 404),
            ({"path": "file1.txt"}, 404),
            ({"path": "/subdir\0/../../../etc"}, 404),
            ({"path": "%2e%2e/test-evil"}, 404),
            ({"dots": "0"}, 400),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        params: dict[str, str],
        status: int,
    ) -> None:
        (root.parent / "test-evil").mkdir()
        async with connector_client(source_config(root)) as http:
            response = await folders(http, **params)

        assert response.status_code == status
        assert response.json()["success"] is False

    async def test_validation_messages(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await http.post(
                "/folders", json={"source": 1, "dots": "0"}
            )

        assert response.json()["data"]["messages"] == [
            "source: Invalid input: expected string, received number",
            "dots: Invalid input",
        ]

    async def test_symlink_outside_root(
        self, connector_client: ClientFactory, root: Path, tmp_path: Path
    ) -> None:
        secret = tmp_path / "secret"
        write_file(secret, "secret.txt", "top secret")
        (root / "evil-link").symlink_to(secret)
        async with connector_client(source_config(root)) as http:
            through_link = await folders(http, path="/evil-link")
            root_listing = await folders(http)

        assert through_link.status_code == 404
        # The folder still lists; the link itself is not shown.
        assert root_listing.status_code == 200
        (source,) = root_listing.json()["data"]["sources"]
        assert "evil-link" not in source["folders"]

    async def test_unreadable_directory(
        self,
        connector_client: ClientFactory,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def unreadable(*_: object) -> list[object]:
            msg = "Permission denied"
            raise PermissionError(msg)

        monkeypatch.setattr(LocalStorageAdapter, "_scan", unreadable)
        async with connector_client(source_config(root)) as http:
            response = await folders(http)

        assert response.status_code == 404
        assert response.json()["data"]["messages"] == ["Path does not exist"]

    async def test_path_rules(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules: JsonValue = [
            {"role": "guest", "FOLDERS": True},
            {"role": "guest", "path": "/private", "FOLDERS": False},
        ]
        async with connector_client(
            source_config(root, accessControl=rules)
        ) as http:
            allowed = await folders(http, path="/")
            denied = await http.post(
                "/folders", json={"source": "test", "path": "/private"}
            )

        assert allowed.status_code == 200
        assert denied.status_code == 403
        assert denied.json()["data"]["messages"] == ["Access denied"]


async def download(http: AsyncClient, **params: str) -> Response:
    return await http.get(
        "/", params={"action": "fileDownload", "source": "test", **params}
    )


class TestFileDownload:
    async def test_streams_large_files(
        self,
        connector_client: ClientFactory,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        body = bytes(range(256)) * 12_000  # about 3 MB
        write_file(root, "big.bin", body)

        def no_full_read(*_: object) -> bytes:
            msg = "the whole file must not be read"
            raise AssertionError(msg)

        monkeypatch.setattr(LocalStorageAdapter, "read", no_full_read)
        async with connector_client(source_config(root)) as http:
            response = await download(http, name="big.bin")

        assert response.status_code == 200
        assert response.headers["content-length"] == str(len(body))
        assert response.content == body

    async def test_unknown_size_is_sent_without_length(
        self,
        connector_client: ClientFactory,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        write_file(root, "a.txt", "abc")
        original = LocalStorageAdapter.stat

        async def sizeless(self: LocalStorageAdapter, path: str) -> StatEntry:
            entry = await original(self, path)
            return StatEntry(entry.path, entry.is_file)

        monkeypatch.setattr(LocalStorageAdapter, "stat", sizeless)
        async with connector_client(source_config(root)) as http:
            response = await download(http, name="a.txt")

        assert response.status_code == 200
        assert "content-length" not in response.headers
        assert response.content == b"abc"

    async def test_file_vanishing_before_the_read(
        self,
        connector_client: ClientFactory,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        write_file(root, "gone.txt", "x")

        async def vanished(*_: object) -> AsyncIterator[bytes]:
            nothing: tuple[bytes, ...] = ()
            for chunk in nothing:  # an async generator that fails at once
                yield chunk
            raise FileWasNotFoundError("gone.txt")

        monkeypatch.setattr(LocalStorageAdapter, "iter_file", vanished)
        async with connector_client(source_config(root)) as http:
            response = await download(http, name="gone.txt")

        assert response.status_code == 404

    async def test_download(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await download(http, name="file1.txt")

        assert response.status_code == 200
        assert response.content == b"one"
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"] == (
            'attachment; filename="file1.txt"'
        )
        assert response.headers["content-transfer-encoding"] == "binary"
        assert response.headers["content-description"] == "File Transfer"
        assert response.headers["content-length"] == "3"

    async def test_subdirectory_and_binary(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            sub = await download(http, path="subdir", name="sub.txt")
            binary = await download(http, name="image.png")

        assert sub.content == b"sub content"
        assert binary.content == b"\x89PNG"

    async def test_unicode_name(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        write_file(root, "отчёт.txt", "данные")
        async with connector_client(source_config(root)) as http:
            response = await download(http, name="отчёт.txt")

        assert response.status_code == 200
        assert response.headers["content-disposition"] == (
            'attachment; filename="_____.txt"; '
            "filename*=UTF-8''%D0%BE%D1%82%D1%87%D1%91%D1%82.txt"
        )

    @pytest.mark.parametrize(
        ("params", "status", "message"),
        [
            ({"name": "missing.txt"}, 404, "File or directory not exists"),
            ({"name": "subdir"}, 400, "It is not a file!"),
            ({"name": "../../../etc/passwd"}, 404, "Path does not exist"),
            (
                {"path": "/subdir", "name": "../file1.txt"},
                404,
                "Path does not exist",
            ),
            ({"name": ""}, 400, "Name parameter is required"),
            ({"source": "nope", "name": "x"}, 404, "Source not found"),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        params: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await download(http, **params)

        assert response.status_code == status
        assert response.json()["data"]["messages"] == [message]

    async def test_missing_name(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await download(http)

        assert response.status_code == 400
        assert response.json()["data"]["messages"] == [
            "name: Invalid input: expected string, received undefined"
        ]

    async def test_symlink_outside_root(
        self, connector_client: ClientFactory, root: Path, tmp_path: Path
    ) -> None:
        write_file(tmp_path / "secret", "secret.txt", "top secret")
        (root / "evil-link").symlink_to(tmp_path / "secret")
        async with connector_client(source_config(root)) as http:
            response = await download(
                http, path="/evil-link", name="secret.txt"
            )

        assert response.status_code == 404

    async def test_requires_download_permission(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules: JsonValue = [{"role": "*", "FILE_DOWNLOAD": False}]
        async with connector_client(
            source_config(root, accessControl=rules)
        ) as http:
            response = await download(http, name="file1.txt")

        assert response.status_code == 403

    async def test_no_sources(self, connector_client: ClientFactory) -> None:
        async with connector_client({"sources": {}}) as http:
            response = await http.get("/fileDownload", params={"name": "x"})

        assert response.status_code == 404

    async def test_null_byte_on_remote_source(self) -> None:
        register_storage_adapter("memory-dl", lambda _: MemoryStorageAdapter())
        config: JsonObject = {
            "sources": {
                "test": {
                    "title": "M",
                    "baseurl": "http://m/",
                    "storageAdapter": "memory-dl",
                }
            }
        }
        async with open_client(make_app(config)) as http:
            response = await download(http, name="a\0b")

        assert response.status_code == 404


async def resolve(http: AsyncClient, url: str) -> Response:
    return await http.get(
        "/", params={"action": "getLocalFileByUrl", "url": url}
    )


class TestGetLocalFileByUrl:
    async def test_root_file(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await resolve(http, f"{BASEURL}file1.txt")

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "data": {
                "code": 220,
                "path": "/",
                "name": "file1.txt",
                "source": "test",
            },
        }

    async def test_subdirectory_and_query(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            sub = await resolve(http, f"{BASEURL}subdir/sub.txt")
            query = await resolve(http, f"{BASEURL}image.png?v=123#x")

        assert sub.json()["data"]["path"] == "/subdir"
        assert sub.json()["data"]["name"] == "sub.txt"
        assert query.json()["data"]["name"] == "image.png"

    async def test_encoded_name(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        write_file(root, "my file.txt", "x")
        async with connector_client(source_config(root)) as http:
            response = await resolve(http, f"{BASEURL}my%20file.txt")

        assert response.json()["data"]["name"] == "my file.txt"

    async def test_second_source(
        self, connector_client: ClientFactory, root: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        write_file(other, "o.txt", "o")
        config = source_config(root)
        sources = config["sources"]
        assert isinstance(sources, dict)
        sources["other"] = {
            "title": "Other",
            "root": str(other),
            "baseurl": "http://cdn.example/other/",
            "name": "other-name",
        }
        async with connector_client(config) as http:
            response = await resolve(http, "http://cdn.example/other/o.txt")

        assert response.json()["data"]["source"] == "other-name"

    @pytest.mark.parametrize(
        ("params", "message"),
        [
            ({}, "Empty url"),
            ({"url": ""}, "Empty url"),
            ({"url": "   "}, "Empty url"),
            ({"url": "not a url"}, "Empty url"),
            ({"url": "http://"}, "Empty url"),
            ({"url": f"{BASEURL}missing.txt"}, "File does not exist"),
            (
                {"url": "http://example.com/some/file.txt"},
                "File does not exist",
            ),
            (
                {"url": f"{BASEURL}../../../etc/passwd"},
                "File does not exist",
            ),
            ({"url": f"{BASEURL}subdir"}, "File does not exist"),
            ({"url": f"{BASEURL}script.exe"}, "File does not exist"),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        params: dict[str, str],
        message: str,
    ) -> None:
        write_file(root, "script.exe", b"MZ")
        async with connector_client(source_config(root)) as http:
            response = await http.get("/getLocalFileByUrl", params=params)

        assert response.status_code == 400
        assert response.json()["data"]["messages"] == [message]

    async def test_url_must_be_a_string(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await http.post("/getLocalFileByUrl", json={"url": 5})

        assert response.json()["data"]["messages"] == ["Empty url"]

    async def test_source_errors_become_missing_file(
        self, connector_client: ClientFactory
    ) -> None:
        config: JsonObject = {
            "sources": {
                "s": {
                    "title": "S",
                    "baseurl": "http://s/",
                    "storageAdapter": "unregistered",
                }
            }
        }
        async with connector_client(config) as http:
            response = await resolve(http, "http://s/a.txt")

        assert response.json()["data"]["messages"] == ["File does not exist"]

    async def test_broken_source_is_skipped(
        self, connector_client: ClientFactory, root: Path, tmp_path: Path
    ) -> None:
        config = source_config(root)
        sources = config["sources"]
        assert isinstance(sources, dict)
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "loop").symlink_to(broken / "loop")
        sources["broken"] = {
            "title": "B",
            "root": str(broken / "loop"),
            "baseurl": "http://b/",
        }
        sources["test"], sources["broken"] = sources["broken"], sources["test"]
        async with connector_client(config) as http:
            response = await resolve(http, f"{BASEURL}file1.txt")

        assert response.status_code == 200


async def test_resolver_rejects_invalid_urls(root: Path) -> None:

    pool = SourcePool(build_config(source_config(root)))
    (source,) = pool._build().values()

    assert await resolve_file_by_url(source, "not a url") is None


async def test_failing_source_is_skipped(
    connector_client: ClientFactory,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    original = resolve_url.resolve_file_by_url
    calls: list[str] = []

    async def flaky(source: Source, url: str) -> ResolvedFile | None:
        calls.append(source.name)
        if len(calls) == 1:
            msg = "boom"
            raise RuntimeError(msg)
        return await original(source, url)

    monkeypatch.setattr(handler, "resolve_file_by_url", flaky)
    config = source_config(root)
    sources = config["sources"]
    assert isinstance(sources, dict)
    sources["again"] = sources["test"]
    async with connector_client(config) as http:
        response = await resolve(http, f"{BASEURL}file1.txt")

    assert calls == ["test", "again"]
    assert response.status_code == 200


async def test_vanishing_entries_are_skipped(root: Path) -> None:
    class Phantom(MemoryStorageAdapter):
        async def stat(self, path: str) -> StatEntry:
            if path == "ghost.txt":
                msg = "gone"
                raise FileNotFoundError(msg)
            return await super().stat(path)

    adapter = Phantom()
    await adapter.write("ghost.txt", b"")
    await adapter.write("real.txt", b"x")
    register_storage_adapter("phantom", lambda _: adapter)
    config: JsonObject = {
        "sources": {
            "test": {
                "title": "P",
                "baseurl": "http://p/",
                "storageAdapter": "phantom",
            }
        },
        "createThumb": False,
    }
    async with open_client(make_app(config)) as http:
        response = await http.get("/files", params={"source": "test"})

    files = response.json()["data"]["sources"][0]["files"]
    assert [item["name"] for item in files] == ["real.txt"]
