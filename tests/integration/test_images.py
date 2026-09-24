"""Image actions, ported from the jodit-nodejs image-* tests."""

import base64
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from jcpy.config.loader import build_config
from jcpy.errors import HttpError
from jcpy.services.images import (
    crop_bytes,
    detect_format,
    load_image,
    remove_thumb,
    resize_bytes,
    save_image,
)
from jcpy.sources import SourcePool
from tests.conftest import BASEURL, service_context, source_config, write_file

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient, Response

    from jcpy.types import JsonObject, JsonValue
    from tests.conftest import ClientFactory


def image(
    size: tuple[int, int] = (200, 100),
    fmt: str = "PNG",
    color: str = "red",
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, fmt)
    return output.getvalue()


def size_of(path: Path) -> tuple[int, int]:
    with Image.open(path) as opened:
        return opened.size


def format_of(path: Path) -> str | None:
    with Image.open(path) as opened:
        return opened.format


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "test"
    write_file(base, "original.png", image())
    write_file(base, "photo.jpg", image(fmt="JPEG"))
    write_file(base, "sub/inner.png", image((40, 40)))
    write_file(base, "broken.png", "not an image")
    write_file(base, "_thumbs/original.png", image((10, 10)))
    return base


def config(root: Path, **settings: JsonValue) -> JsonObject:
    return source_config(root, defaultFilesKey="files", **settings)


async def call(http: AsyncClient, action: str, **params: str) -> Response:
    return await http.get(
        "/", params={"action": action, "source": "test", **params}
    )


def messages(response: Response) -> list[str]:
    result: list[str] = response.json()["data"]["messages"]
    return result


class TestResize:
    async def test_in_place(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http,
                "imageResize",
                name="original.png",
                **{"box[w]": "50", "box[h]": "30"},
            )

        assert response.json() == {
            "success": True,
            "data": {"code": 220, "newPath": f"{BASEURL}original.png"},
        }
        assert size_of(root / "original.png") == (50, 30)
        assert format_of(root / "original.png") == "PNG"
        assert not (root / "original.png.tmp").exists()
        assert not (root / "_thumbs" / "original.png").exists()

    @pytest.mark.parametrize(
        ("new_name", "stored"),
        [("resized.png", "resized.png"), ("resized", "resized.png")],
    )
    async def test_new_name(
        self,
        connector_client: ClientFactory,
        root: Path,
        new_name: str,
        stored: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageResize",
                json={
                    "source": "test",
                    "name": "original.png",
                    "newname": new_name,
                    "box": {"w": 50, "h": 50},
                },
            )

        assert response.json()["data"]["newPath"] == f"{BASEURL}{stored}"
        assert size_of(root / stored) == (50, 50)
        assert size_of(root / "original.png") == (200, 100)

    async def test_jpeg_and_subdirectory(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            jpeg = await call(
                http,
                "imageResize",
                name="photo.jpg",
                **{"box[w]": "20", "box[h]": "10"},
            )
            nested = await call(
                http,
                "imageResize",
                path="sub",
                name="inner.png",
                **{"box[w]": "4", "box[h]": "4"},
            )

        assert jpeg.status_code == 200
        assert format_of(root / "photo.jpg") == "JPEG"
        assert nested.json()["data"]["newPath"] == f"{BASEURL}sub/inner.png"
        assert size_of(root / "sub" / "inner.png") == (4, 4)

    @pytest.mark.parametrize(
        ("params", "status", "message"),
        [
            (
                {"name": "original.png", "box[h]": "5"},
                400,
                "box.w: Invalid input: expected number, received undefined",
            ),
            (
                {"name": "original.png", "box[w]": "0", "box[h]": "5"},
                400,
                "box.w: Too small: expected number to be >0",
            ),
            (
                {"name": "missing.png", "box[w]": "5", "box[h]": "5"},
                404,
                "File not exists",
            ),
            (
                {"name": "sub", "box[w]": "5", "box[h]": "5"},
                404,
                "File not exists",
            ),
            (
                {"name": "../../etc/passwd", "box[w]": "5", "box[h]": "5"},
                404,
                "Path does not exist",
            ),
            (
                {"name": "broken.png", "box[w]": "5", "box[h]": "5"},
                400,
                "Unable to resize image: "
                "Input buffer contains unsupported image format",
            ),
            (
                {
                    "source": "nope",
                    "name": "a.png",
                    "box[w]": "5",
                    "box[h]": "5",
                },
                404,
                "Source not found",
            ),
            (
                {"name": "", "box[w]": "5", "box[h]": "5"},
                400,
                "Name parameter is required",
            ),
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
        async with connector_client(config(root)) as http:
            response = await call(http, "imageResize", **params)

        assert response.status_code == status
        assert messages(response)[0] == message

    async def test_permissions(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules: JsonValue = [
            {
                "role": "*",
                "path": str(root / "locked.png"),
                "IMAGE_RESIZE": False,
            }
        ]
        async with connector_client(config(root, accessControl=rules)) as http:
            denied = await call(
                http,
                "imageResize",
                name="original.png",
                newname="locked.png",
                **{"box[w]": "5", "box[h]": "5"},
            )
            dir_denied_rules: JsonValue = [
                {"role": "*", "IMAGE_RESIZE": False}
            ]

        assert denied.status_code == 403
        assert not (root / "locked.png").exists()
        async with connector_client(
            config(root, accessControl=dir_denied_rules)
        ) as http:
            response = await call(
                http,
                "imageResize",
                name="original.png",
                **{"box[w]": "5", "box[h]": "5"},
            )
        assert response.status_code == 403


class TestCrop:
    async def test_in_place_and_new_name(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        box = {"box[x]": "10", "box[y]": "20", "box[w]": "30", "box[h]": "40"}
        async with connector_client(config(root)) as http:
            copy = await call(
                http, "imageCrop", name="original.png", newname="part", **box
            )
            corner = await call(
                http,
                "imageCrop",
                name="original.png",
                **{"box[x]": "0", "box[y]": "0", "box[w]": "5", "box[h]": "6"},
            )

        assert copy.json()["data"]["newPath"] == f"{BASEURL}part.png"
        assert size_of(root / "part.png") == (30, 40)
        assert corner.status_code == 200
        assert size_of(root / "original.png") == (5, 6)

    async def test_jpeg(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageCrop",
                json={
                    "source": "test",
                    "name": "photo.jpg",
                    "box": {"x": "1", "y": "2", "w": "3", "h": "4"},
                },
            )

        assert response.status_code == 200
        assert size_of(root / "photo.jpg") == (3, 4)
        assert format_of(root / "photo.jpg") == "JPEG"

    @pytest.mark.parametrize(
        ("box", "message"),
        [
            (
                {"box[y]": "0", "box[w]": "5", "box[h]": "5"},
                "box.x: Invalid input: expected number, received undefined",
            ),
            (
                {"box[x]": "-1", "box[y]": "0", "box[w]": "5", "box[h]": "5"},
                "box.x: Too small: expected number to be >=0",
            ),
            (
                {
                    "box[x]": "190",
                    "box[y]": "0",
                    "box[w]": "20",
                    "box[h]": "5",
                },
                "Unable to crop image: extract_area: bad extract area",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        box: dict[str, str],
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "imageCrop", name="original.png", **box
            )

        assert response.status_code == 400
        assert messages(response)[0] == message
        assert size_of(root / "original.png") == (200, 100)


class TestSave:
    async def test_save_as_new_file(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/",
                data={
                    "action": "imageSave",
                    "source": "test",
                    "newname": "edited-image.png",
                },
                files=[("files[0]", ("x.png", image((120, 90)), "image/png"))],
            )

        assert response.json() == {
            "success": True,
            "data": {
                "code": 220,
                "newPath": f"{BASEURL}edited-image.png",
                "name": "edited-image.png",
            },
        }
        assert size_of(root / "edited-image.png") == (120, 90)

    async def test_overwrite_drops_stale_thumbnail(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageSave",
                data={"name": "original.png"},
                files=[("files", ("x.png", image((64, 32)), "image/png"))],
            )

        assert response.status_code == 200
        assert size_of(root / "original.png") == (64, 32)
        assert not (root / "_thumbs" / "original.png").exists()

    @pytest.mark.parametrize(
        ("data", "stored"),
        [
            ({"name": "original.png", "newname": "  copy  "}, "copy.png"),
            ({"newname": "noext"}, "noext.jpeg"),
            ({"newname": "../escape.png"}, ".._escape.png"),
        ],
    )
    async def test_target_names(
        self,
        connector_client: ClientFactory,
        root: Path,
        data: dict[str, str],
        stored: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageSave",
                data=data,
                files=[("files", ("x", image(fmt="JPEG"), "image/jpeg"))],
            )

        assert response.json()["data"]["name"] == stored
        assert (root / stored).exists()

    @pytest.mark.parametrize(
        ("data", "files", "status", "message"),
        [
            ({"name": "a.png"}, [], 400, "No image has been uploaded"),
            (
                {"name": "a.png"},
                [("files", ("a.png", b"not an image", "image/png"))],
                400,
                "Provided data is not a valid image",
            ),
            (
                {},
                [("files", ("a.png", image(), "image/png"))],
                400,
                'Either "name" or "newname" is required',
            ),
            (
                {"name": "a.png", "newname": "   "},
                [("files", ("a.png", image(), "image/png"))],
                200,
                "",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        data: dict[str, str],
        files: list[tuple[str, tuple[str, bytes, str]]],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageSave",
                data=data,
                files=files or [("other", ("a.txt", b"x", "text/plain"))],
            )

        assert response.status_code == status
        if message:
            assert messages(response) == [message]

    async def test_whitespace_new_name_without_name(self, root: Path) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]
        context = service_context()

        with pytest.raises(HttpError, match="Either"):
            await save_image(context, source, image(), "", "  ", "/")

    async def test_get_is_rejected(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "imageSave", name="a.png")

        assert response.status_code == 405
        assert messages(response) == ["imageSave requires a POST request"]


class TestLoad:
    async def test_data_url(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageLoad",
                json={"source": "test", "path": "sub", "name": "inner.png"},
            )

        data = response.json()["data"]
        assert data["name"] == "inner.png"
        prefix, encoded = data["content"].split(",", 1)
        assert prefix == "data:image/png;base64"
        assert (
            base64.b64decode(encoded)
            == (root / "sub" / "inner.png").read_bytes()
        )

    async def test_unknown_extension(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        write_file(root, "doc.txt", "text")
        async with connector_client(config(root)) as http:
            response = await http.post("/imageLoad", json={"name": "doc.txt"})

        assert response.json()["data"]["content"].startswith(
            "data:application/octet-stream;base64,"
        )

    @pytest.mark.parametrize(
        ("body", "status", "message"),
        [
            ({"name": "missing.png"}, 404, "File not exists"),
            ({"name": "sub"}, 404, "File not exists"),
            ({"name": "../x.png"}, 404, "Path does not exist"),
            ({"name": ""}, 400, "Name parameter is required"),
            (
                {},
                400,
                "name: Invalid input: expected string, received undefined",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        body: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post("/imageLoad", json=body)

        assert response.status_code == status
        assert messages(response) == [message]

    async def test_get_is_rejected(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "imageLoad", name="original.png")

        assert response.status_code == 405
        assert messages(response) == ["imageLoad requires a POST request"]

    async def test_permission(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules: JsonValue = [
            {"role": "*", "path": str(root), "IMAGE_LOAD": False}
        ]
        async with connector_client(config(root, accessControl=rules)) as http:
            response = await http.post(
                "/imageLoad", json={"name": "original.png"}
            )

        assert response.status_code == 403


class TestImageHelpers:
    def test_resize_and_crop_keep_format(self) -> None:
        for fmt in ("PNG", "JPEG", "GIF", "WEBP"):
            resized = resize_bytes(image(fmt=fmt), 10, 20)
            cropped = crop_bytes(image(fmt=fmt), 0, 0, 5, 5)
            for data in (resized, cropped):
                with Image.open(BytesIO(data)) as opened:
                    assert opened.format == fmt

    def test_jpeg_from_transparent_image(self) -> None:
        output = BytesIO()
        Image.new("RGBA", (8, 8)).save(output, "PNG")
        with Image.open(BytesIO(output.getvalue())) as source:
            rgba_as_jpeg = BytesIO()
            source.convert("RGB").save(rgba_as_jpeg, "JPEG")
        assert resize_bytes(rgba_as_jpeg.getvalue(), 4, 4)

    def test_detect_format(self) -> None:
        assert detect_format(image(fmt="JPEG")) == "jpeg"
        assert detect_format(b"nope") is None


class TestStorageFailures:
    async def test_parent_name_is_rejected(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageLoad", json={"path": "sub", "name": ".."}
            )

        assert response.status_code == 404
        assert messages(response) == ["Path does not exist"]

    async def test_save_over_a_directory(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        (root / "taken.png").mkdir()
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/imageSave",
                data={"newname": "taken.png"},
                files=[("files", ("x.png", image(), "image/png"))],
            )

        assert response.status_code == 400
        assert messages(response)[0].startswith("Unable to save image: ")

    async def test_existence_check_failure_writes_directly(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]

        async def broken(path: str) -> bool:
            msg = "offline"
            raise OSError(msg)

        monkeypatch.setattr(source.storage, "file_exists", broken)
        context = service_context()

        written = await save_image(
            context,
            source,
            image((7, 7)),
            "",
            "fresh.png",
            "/",
        )

        assert written == "fresh.png"
        assert size_of(root / "fresh.png") == (7, 7)

    async def test_read_failure_after_stat(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]

        async def vanished(path: str) -> bytes:
            msg = "gone"
            raise OSError(msg)

        monkeypatch.setattr(source.storage, "read", vanished)
        context = service_context()

        with pytest.raises(HttpError, match="File not exists"):
            await load_image(context, source, "original.png", "/")

    async def test_thumbnail_cleanup_errors_are_ignored(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]

        async def broken(path: str) -> None:
            msg = "read-only"
            raise OSError(msg)

        monkeypatch.setattr(source.storage, "delete_file", broken)

        await remove_thumb(source, "original.png")

        assert (root / "_thumbs" / "original.png").exists()
