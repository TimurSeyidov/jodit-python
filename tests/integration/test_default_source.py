"""``source=default``, sent by Jodit for the root item of the folder tree."""

from typing import TYPE_CHECKING

import pytest

from tests.conftest import write_file

if TYPE_CHECKING:
    from pathlib import Path

    from jcpy.types import JsonObject
    from tests.conftest import ClientFactory


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_file(first, "one.txt", "1")
    write_file(second, "two.txt", "2")
    return first, second


def local(root: Path, baseurl: str) -> JsonObject:
    return {"title": root.name, "root": str(root), "baseurl": baseurl}


def two_sources(first: Path, second: Path) -> JsonObject:
    return {
        "sources": {
            "main": local(first, "http://x/first/"),
            "extra": local(second, "http://x/second/"),
        }
    }


def source_names(body: JsonObject) -> list[str]:
    data = body["data"]
    assert isinstance(data, dict)
    sources = data["sources"]
    assert isinstance(sources, list)
    return [str(item["name"]) for item in sources if isinstance(item, dict)]


async def test_query_string_lists_all_sources(
    connector_client: ClientFactory, roots: tuple[Path, Path]
) -> None:
    async with connector_client(two_sources(*roots)) as http:
        files = await http.get(
            "/", params={"action": "files", "source": "default"}
        )
        folders = await http.get("/folders?source=default")

    assert files.status_code == 200, files.text
    assert source_names(files.json()) == ["main", "extra"]
    assert folders.status_code == 200, folders.text
    assert source_names(folders.json()) == ["main", "extra"]


async def test_urlencoded_body(
    connector_client: ClientFactory, roots: tuple[Path, Path]
) -> None:
    async with connector_client(two_sources(*roots)) as http:
        files = await http.post(
            "/", data={"action": "files", "source": "default"}
        )
        permissions = await http.post(
            "/", data={"action": "permissions", "source": "default"}
        )
        created = await http.post(
            "/",
            data={
                "action": "folderCreate",
                "source": "default",
                "name": "new",
            },
        )

    assert files.status_code == 200, files.text
    assert source_names(files.json()) == ["main", "extra"]
    assert permissions.status_code == 200, permissions.text
    assert created.status_code == 200, created.text
    assert (roots[0] / "new").is_dir()
    assert not (roots[1] / "new").exists()


async def test_multipart_upload_lands_in_the_first_source(
    connector_client: ClientFactory, roots: tuple[Path, Path]
) -> None:
    async with connector_client(two_sources(*roots)) as http:
        response = await http.post(
            "/",
            data={"action": "fileUpload", "source": "default"},
            files=[("files[0]", ("up.txt", b"up", "text/plain"))],
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["baseurl"] == "http://x/first/"
    assert (roots[0] / "up.txt").read_bytes() == b"up"
    assert not (roots[1] / "up.txt").exists()


async def test_configured_source_named_default_wins(
    connector_client: ClientFactory, roots: tuple[Path, Path]
) -> None:
    first, second = roots
    config: JsonObject = {
        "sources": {
            "main": local(first, "http://x/first/"),
            "default": local(second, "http://x/second/"),
        }
    }
    async with connector_client(config) as http:
        files = await http.get("/files?source=default")
        upload = await http.post(
            "/fileUpload",
            data={"source": "default"},
            files=[("files[0]", ("up.txt", b"up", "text/plain"))],
        )

    assert files.status_code == 200, files.text
    assert source_names(files.json()) == ["default"]
    assert upload.status_code == 200, upload.text
    assert (second / "up.txt").exists()
    assert not (first / "up.txt").exists()


async def test_other_unknown_sources_are_still_refused(
    connector_client: ClientFactory, roots: tuple[Path, Path]
) -> None:
    async with connector_client(two_sources(*roots)) as http:
        response = await http.get("/files?source=Default")

    assert response.status_code == 404
    assert response.json()["data"]["messages"] == ["Source not found"]
