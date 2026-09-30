"""Rejected uploads leave existing files alone; saved names obey rules."""

from io import BytesIO
from typing import TYPE_CHECKING, BinaryIO

import pytest
from PIL import Image

from jcpy.helpers import ssrf
from jcpy.storage.local import LocalStorageAdapter
from tests.conftest import source_config, write_file

if TYPE_CHECKING:
    from pathlib import Path

    from jcpy.types import JsonObject, JsonValue
    from tests.conftest import ClientFactory


def replace_config(root: Path, **settings: JsonValue) -> JsonObject:
    return source_config(
        root,
        saveSameFileNameStrategy="replace",
        allowPrivateNetworkUploads=True,
        **settings,
    )


def gif_with_payload() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1, 1), "red").save(output, "GIF")
    return output.getvalue() + b"<script>alert(1)</script><?php system(1); ?>"


EVIL_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
    b'<script>alert(2)</script><a href="javascript:alert(3)"><rect/></a>'
    b"</svg>"
)


async def test_svg_uploads_are_cleaned(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    async with connector_client(source_config(tmp_path)) as http:
        response = await http.post(
            "/fileUpload", files={"files[0]": ("logo.svg", EVIL_SVG)}
        )

    assert response.status_code == 200, response.text
    stored = (tmp_path / "logo.svg").read_bytes()
    assert b"<rect" in stored
    assert b"alert" not in stored


async def test_svg_cleaning_can_be_turned_off(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    config = source_config(tmp_path, sanitizeSvg=False)

    async with connector_client(config) as http:
        await http.post(
            "/fileUpload", files={"files[0]": ("logo.svg", EVIL_SVG)}
        )

    assert (tmp_path / "logo.svg").read_bytes() == EVIL_SVG


async def test_invalid_svg_keeps_the_existing_file(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    write_file(tmp_path, "logo.svg", "<svg>kept</svg>")

    async with connector_client(replace_config(tmp_path)) as http:
        response = await http.post(
            "/fileUpload",
            files={
                "files[0]": ("a.txt", b"fine"),
                "files[1]": ("logo.svg", b"<html>not an svg</html>"),
            },
        )

    assert response.status_code == 400
    assert response.json()["data"]["messages"] == [
        "File is not a valid SVG image: the root element is not <svg>"
    ]
    assert (tmp_path / "logo.svg").read_text() == "<svg>kept</svg>"
    # Nothing is written when any file of the upload is refused.
    assert not (tmp_path / "a.txt").exists()


async def test_image_save_as_svg_needs_svg_data(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    async with connector_client(source_config(tmp_path)) as http:
        response = await http.post(
            "/imageSave",
            data={"newname": "edited.svg"},
            files={"files[0]": ("edited.gif", gif_with_payload())},
        )

    assert response.status_code == 400
    assert not (tmp_path / "edited.svg").exists()


async def test_denied_upload_keeps_the_existing_file(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    write_file(tmp_path, "contract.pdf", "signed")
    config = replace_config(
        tmp_path,
        accessControl=[{"extensions": "pdf", "FILE_UPLOAD": False}],
    )

    async with connector_client(config) as http:
        response = await http.post(
            "/fileUpload", files={"files[0]": ("contract.pdf", b"forged")}
        )

    assert response.status_code == 403
    assert (tmp_path / "contract.pdf").read_text() == "signed"


async def test_oversized_upload_keeps_the_existing_file(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    write_file(tmp_path, "notes.txt", "original")
    config = replace_config(tmp_path, maxUploadFileSize="10b")

    async with connector_client(config) as http:
        response = await http.post(
            "/fileUpload", files={"files[0]": ("notes.txt", b"x" * 100)}
        )

    assert response.status_code == 403
    assert response.json()["data"]["messages"] == [
        "File size exceeds the allowable"
    ]
    assert (tmp_path / "notes.txt").read_text() == "original"


async def test_rejected_file_in_a_batch_writes_nothing(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    write_file(tmp_path, "a.txt", "original a")

    async with connector_client(replace_config(tmp_path)) as http:
        response = await http.post(
            "/fileUpload",
            files={
                "files[0]": ("a.txt", b"new a"),
                "files[1]": ("b.exe", b"binary"),
            },
        )

    assert response.status_code == 403
    assert (tmp_path / "a.txt").read_text() == "original a"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.txt"]


async def test_denied_remote_upload_keeps_the_existing_file(
    connector_client: ClientFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def download_to(_url: str, file: BinaryIO, **__: object) -> int:
        return file.write(b"forged")

    monkeypatch.setattr(ssrf, "download_to", download_to)
    write_file(tmp_path, "contract.pdf", "signed")
    config = replace_config(
        tmp_path,
        accessControl=[{"extensions": "pdf", "FILE_UPLOAD": False}],
    )

    async with connector_client(config) as http:
        response = await http.get(
            "/fileUploadRemote",
            params={"url": "https://example.com/contract.pdf"},
        )

    assert response.status_code == 403
    assert (tmp_path / "contract.pdf").read_text() == "signed"


@pytest.mark.parametrize("name", ["page.html", "page.HTM", "app.js"])
async def test_pages_and_scripts_are_refused_by_default(
    connector_client: ClientFactory, tmp_path: Path, name: str
) -> None:
    async with connector_client(source_config(tmp_path)) as http:
        response = await http.post(
            "/fileUpload",
            files={"files[0]": (name, b"<script>alert(1)</script>")},
        )

    assert response.status_code == 403
    assert response.json()["data"]["messages"] == [
        "File type is not in white list"
    ]
    assert not (tmp_path / name).exists()


async def test_pages_can_be_allowed_explicitly(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    config = source_config(tmp_path, extensions=["html"])

    async with connector_client(config) as http:
        response = await http.post(
            "/fileUpload", files={"files[0]": ("page.html", b"<p>x</p>")}
        )

    assert response.status_code == 200, response.text
    assert (tmp_path / "page.html").read_bytes() == b"<p>x</p>"


@pytest.mark.parametrize("new_name", ["shell.php", "page.exe", "evil.html"])
async def test_image_save_obeys_extensions(
    connector_client: ClientFactory, tmp_path: Path, new_name: str
) -> None:
    config = source_config(tmp_path, extensions=["jpg", "png", "gif"])

    async with connector_client(config) as http:
        response = await http.post(
            "/imageSave",
            data={"newname": new_name},
            files={"files[0]": ("edited.gif", gif_with_payload())},
        )

    assert response.status_code == 403
    assert response.json()["data"]["messages"] == [
        "File type is not in white list"
    ]
    assert not (tmp_path / new_name).exists()


async def test_image_save_with_allowed_extension_still_works(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    async with connector_client(source_config(tmp_path)) as http:
        response = await http.post(
            "/imageSave",
            data={"newname": "edited"},
            files={"files[0]": ("edited.gif", gif_with_payload())},
        )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "edited.gif"


async def test_uploads_are_streamed(
    connector_client: ClientFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_buffered_write(*_: object) -> None:
        msg = "uploads must be streamed"
        raise AssertionError(msg)

    monkeypatch.setattr(LocalStorageAdapter, "write", no_buffered_write)
    body = b"x" * 300_000
    async with connector_client(source_config(tmp_path)) as http:
        response = await http.post(
            "/fileUpload", files={"files[0]": ("big.txt", body)}
        )

    assert response.status_code == 200, response.text
    assert (tmp_path / "big.txt").read_bytes() == body
