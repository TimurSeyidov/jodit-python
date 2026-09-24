"""Rejected uploads leave existing files alone; saved names obey rules."""

from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from jcpy.helpers import ssrf
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
    async def download(*_: object, **__: object) -> bytes:
        return b"forged"

    monkeypatch.setattr(ssrf, "download", download)
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
