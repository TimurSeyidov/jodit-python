"""``files`` action, ported from jodit-nodejs files.test.ts."""

import asyncio
import os
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from jcpy.helpers.js import format_datetime
from tests.conftest import (
    BASEURL,
    make_app,
    open_client,
    source_config,
    write_file,
)

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient

    from jcpy.storage.base import StatEntry
    from jcpy.types import JsonObject, JsonValue
    from tests.conftest import ClientFactory


def png(size: tuple[int, int] = (400, 200), fmt: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "blue").save(output, fmt)
    return output.getvalue()


def touch(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "files"
    write_file(base, "test.txt", "hello")
    write_file(base, "image.png", png())
    write_file(base, "doc.docx", b"PK")
    write_file(base, "script.exe", b"MZ")
    write_file(base, ".tmb/cache.txt", "x")
    write_file(base, "subfolder/inner.txt", "inner")
    write_file(base, "subfolder/somefolder/deep.txt", "deep")
    write_file(base, "subfolder/image.png", png((50, 50)))
    for index, name in enumerate(("test.txt", "image.png", "doc.docx")):
        touch(base / name, 1_700_000_000 + index * 100)
    return base


async def listing(
    http: AsyncClient, params: dict[str, str] | None = None
) -> JsonObject:
    response = await http.get(
        "/", params={"action": "files", "source": "test", **(params or {})}
    )
    assert response.status_code == 200, response.text
    source: JsonObject = response.json()["data"]["sources"][0]
    return source


def items(source: JsonObject) -> list[JsonObject]:
    files = source["files"]
    assert isinstance(files, list)
    return [item for item in files if isinstance(item, dict)]


def names(source: JsonObject) -> list[JsonValue]:
    return [item["name"] for item in items(source)]


async def test_lists_root(connector_client: ClientFactory, root: Path) -> None:
    async with connector_client(source_config(root)) as http:
        response = await http.get(
            "/", params={"action": "files", "source": "test"}
        )

    body = response.json()
    assert body["success"] is True
    assert list(body["data"]) == ["code", "sources"]
    source = body["data"]["sources"][0]
    assert {k: source[k] for k in ("name", "title", "baseurl", "path")} == {
        "name": "test",
        "title": "Test Files",
        "baseurl": BASEURL,
        "path": "/",
    }
    by_name = {item["name"]: item for item in source["files"]}
    assert set(by_name) == {"test.txt", "image.png", "doc.docx"}
    assert by_name["test.txt"] == {
        "file": "test.txt",
        "name": "test.txt",
        "type": "file",
        "isImage": False,
        "size": "5B",
        "changed": format_datetime(1_700_000_000_000, "M/D/YYYY h:mm:ss A"),
        "thumb": "_thumbs/test.txt.svg",
    }
    assert by_name["image.png"]["type"] == "image"
    assert by_name["image.png"]["isImage"] is True
    assert by_name["image.png"]["thumb"] == "_thumbs/image.png"


async def test_default_sort_is_newest_first(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        source = await listing(http)

    assert names(source) == ["doc.docx", "image.png", "test.txt"]


async def test_subfolder_with_folders_on_top(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        source = await listing(
            http,
            {
                "path": "subfolder",
                "mods[withFolders]": "true",
                "mods[foldersPosition]": "top",
                "mods[sortBy]": "name-asc",
            },
        )

    assert source["path"] == "subfolder"
    files = items(source)
    assert files[0] == {
        "file": "somefolder",
        "name": "somefolder",
        "type": "folder",
        "thumb": "_thumbs/somefolder.svg",
    }
    assert names(source) == ["somefolder", "image.png", "inner.txt"]
    assert files[1]["thumb"] == "_thumbs/image.png"


async def test_folders_are_hidden_by_default(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        source = await listing(http, {"path": "subfolder"})

    assert "somefolder" not in names(source)


@pytest.mark.parametrize(
    ("sort_by", "expected"),
    [
        ("name-asc", ["doc.docx", "image.png", "test.txt"]),
        ("name-desc", ["test.txt", "image.png", "doc.docx"]),
        ("changed-asc", ["test.txt", "image.png", "doc.docx"]),
        ("changed-desc", ["doc.docx", "image.png", "test.txt"]),
    ],
)
async def test_sorting(
    connector_client: ClientFactory,
    root: Path,
    sort_by: str,
    expected: list[str],
) -> None:
    async with connector_client(source_config(root)) as http:
        source = await listing(http, {"mods[sortBy]": sort_by})

    assert names(source) == expected


async def test_sort_by_size(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        ascending = await listing(http, {"mods[sortBy]": "size-asc"})
        descending = await listing(http, {"mods[sortBy]": "size-desc"})

    assert names(ascending)[:2] == ["doc.docx", "test.txt"]
    assert names(descending)[0] == "image.png"


async def test_folders_at_bottom(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        source = await listing(
            http,
            {
                "mods[withFolders]": "true",
                "mods[foldersPosition]": "bottom",
            },
        )

    assert names(source)[-1] == "subfolder"


async def test_only_images(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        source = await listing(http, {"mods[onlyImages]": "true"})

    assert names(source) == ["image.png"]


async def test_offset_and_limit(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        limited = await listing(
            http, {"mods[sortBy]": "name-asc", "mods[limit]": "2"}
        )
        paged = await listing(
            http,
            {
                "mods[sortBy]": "name-asc",
                "mods[offset]": "1",
                "mods[limit]": "1",
            },
        )

    assert names(limited) == ["doc.docx", "image.png"]
    assert names(paged) == ["image.png"]


@pytest.mark.parametrize(
    ("field", "message"),
    [("offset", "Offset is not numeric"), ("limit", "limit is not numeric")],
)
async def test_non_numeric_paging(
    connector_client: ClientFactory, root: Path, field: str, message: str
) -> None:
    async with connector_client(source_config(root)) as http:
        response = await http.get(
            "/files", params={"source": "test", f"mods[{field}]": "abc"}
        )

    assert response.status_code == 422
    assert response.json()["data"]["messages"] == [message]


async def test_filter_word(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        found = await listing(http, {"mods[filterWord]": "IMAGE"})
        nothing = await listing(http, {"mods[filterWord]": "zzz"})
        empty = await listing(http, {"mods[filterWord]": ""})

    assert names(found) == ["image.png"]
    assert names(nothing) == []
    assert len(names(empty)) == 3


async def test_editor_style_post(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        response = await http.post(
            "/",
            json={
                "action": "files",
                "source": "test",
                "path": "/",
                "mods": {
                    "withFolders": True,
                    "onlyImages": False,
                    "foldersPosition": "top",
                    "sortBy": "name-asc",
                    "filterWord": "",
                    "offset": 0,
                    "limit": 100,
                },
            },
        )

    assert response.status_code == 200
    source = response.json()["data"]["sources"][0]
    assert names(source) == ["subfolder", "doc.docx", "image.png", "test.txt"]


async def test_urlencoded_post(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        response = await http.post(
            "/",
            content="action=files&source=test&mods[sortBy]=name-asc",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    files = response.json()["data"]["sources"][0]["files"]
    assert files[0]["thumb"] == "_thumbs/doc.docx.svg"


async def test_all_sources_without_name(
    connector_client: ClientFactory, root: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    write_file(other, "o.txt", "o")
    config = source_config(root)
    sources = config["sources"]
    assert isinstance(sources, dict)
    sources["other"] = {
        "title": "Other",
        "root": str(other),
        "baseurl": "http://o/",
    }
    async with connector_client(config) as http:
        response = await http.get("/files")

    data = response.json()["data"]["sources"]
    assert [source["name"] for source in data] == ["test", "other"]


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"source": "nope"}, 404),
        ({"path": "missing"}, 404),
        ({"path": "../"}, 404),
        ({"path": "test.txt"}, 404),
        ({"mods[sortBy]": "random"}, 400),
    ],
)
async def test_errors(
    connector_client: ClientFactory,
    root: Path,
    params: dict[str, str],
    status: int,
) -> None:
    async with connector_client(source_config(root)) as http:
        response = await http.get(
            "/", params={"action": "files", "source": "test", **params}
        )

    assert response.status_code == status
    assert response.json()["success"] is False


async def test_validation_message(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        response = await http.post("/files", json={"source": 1, "mods": 5})

    assert response.status_code == 400
    assert response.json()["data"]["messages"] == [
        "Validation failed Invalid input: expected string, received number,"
        "Invalid input"
    ]


async def test_thumbnails_are_created_once(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(source_config(root)) as http:
        await listing(http)
        thumb = root / "_thumbs" / "image.png"
        first = thumb.stat().st_mtime_ns
        await asyncio.sleep(0.01)
        await listing(http)

    assert thumb.stat().st_mtime_ns == first
    assert (
        (root / "_thumbs" / "test.txt.svg").read_text().startswith("\n\t<svg")
    )
    with Image.open(thumb) as image:
        assert image.size == (250, 125)


async def test_webp_thumbnail_is_webp(
    connector_client: ClientFactory, root: Path
) -> None:
    write_file(root, "photo.webp", png(fmt="WEBP"))
    async with connector_client(source_config(root)) as http:
        await listing(http)

    with Image.open(root / "_thumbs" / "photo.webp") as image:
        assert image.format == "WEBP"


async def test_thumbnail_fallbacks(
    connector_client: ClientFactory, root: Path
) -> None:
    write_file(root, "vector.svg", "<svg/>")
    write_file(root, "broken.jpg", "not an image")
    async with connector_client(source_config(root)) as http:
        source = await listing(http)

    thumbs = {item["name"]: item.get("thumb") for item in items(source)}
    assert thumbs["vector.svg"] == "vector.svg"
    assert thumbs["broken.jpg"] == "broken.jpg"


async def test_thumbnails_disabled(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(
        source_config(root, createThumb=False)
    ) as http:
        source = await listing(http)

    assert all("thumb" not in item for item in items(source))
    assert not (root / "_thumbs").exists()


async def test_svg_icons_disabled(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(
        source_config(root, generateSvgThumbs=False)
    ) as http:
        source = await listing(http, {"mods[sortBy]": "name-asc"})

    assert items(source)[0]["thumb"] == "doc.docx"


async def test_thumbnail_limit_per_request(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    for index in range(5):
        write_file(tmp_path, f"f{index}.txt", "x")
    async with connector_client(
        source_config(tmp_path, safeThumbsCountInOneTime=1)
    ) as http:
        source = await listing(http)

    with_thumbs = [item for item in items(source) if "thumb" in item]
    assert len(with_thumbs) == 2


async def test_custom_svg_generator(root: Path) -> None:
    calls: list[tuple[str, int, int]] = []

    def generator(entry: StatEntry, width: int, height: int) -> str:
        calls.append((entry.path, width, height))
        return "<svg>custom</svg>"

    app = make_app(
        source_config(root, svgThumbWidth=64, svgThumbHeight=32),
        svg_generator=generator,
    )
    async with open_client(app) as http:
        await listing(http)

    assert ("test.txt", 64, 32) in calls
    assert (root / "_thumbs" / "test.txt.svg").read_text() == (
        "<svg>custom</svg>"
    )


async def test_per_source_extensions(
    connector_client: ClientFactory, root: Path
) -> None:
    config = source_config(root)
    sources = config["sources"]
    assert isinstance(sources, dict)
    test = sources["test"]
    assert isinstance(test, dict)
    test["extensions"] = ["txt"]
    async with connector_client(config) as http:
        source = await listing(http)

    assert names(source) == ["test.txt"]


async def test_excluded_directories(
    connector_client: ClientFactory, root: Path
) -> None:
    (root / ".tmb").mkdir(exist_ok=True)
    async with connector_client(source_config(root)) as http:
        source = await listing(http, {"mods[withFolders]": "true"})

    assert ".tmb" not in names(source)
    assert "_thumbs" not in names(source)
