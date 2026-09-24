"""Real answers match the documented schemas."""

from typing import TYPE_CHECKING

from PIL import Image

from jcpy.openapi import models

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel

    from tests.conftest import ClientFactory

from tests.conftest import BASEURL, source_config, write_file


def _check(model: type[BaseModel], payload: object) -> None:
    parsed = model.model_validate(payload)

    # Nothing undocumented, nothing coerced.
    assert parsed.model_dump(by_alias=True, exclude_unset=True) == payload


async def test_answers_validate(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    write_file(tmp_path, "a.txt", b"hello")
    Image.new("RGB", (8, 6)).save(tmp_path / "pic.png")
    config = source_config(tmp_path)

    async with connector_client(config) as http:
        files = await http.get("/files", params={"source": "test"})
        folders = await http.get("/folders", params={"source": "test"})
        permissions = await http.get("/permissions")
        created = await http.get("/folderCreate", params={"name": "sub"})
        upload = await http.post(
            "/fileUpload", files={"files[0]": ("b.txt", b"hi")}
        )
        removed = await http.get("/fileRemove", params={"name": "b.txt"})
        missing = await http.get("/fileRemove", params={"name": "x.txt"})
        resized = await http.get(
            "/imageResize",
            params={"name": "pic.png", "box[w]": "4", "box[h]": "3"},
        )
        loaded = await http.post("/imageLoad", json={"name": "pic.png"})
        local = await http.get("/getLocalFileByUrl", params={"url": BASEURL})
        ping = await http.get("/ping")

    _check(models.FilesResponse, files.json())
    _check(models.FoldersResponse, folders.json())
    _check(models.PermissionsResponse, permissions.json())
    _check(models.MessagesResponse, created.json())
    _check(models.UploadResponse, upload.json())
    _check(models.DoneResponse, removed.json())
    _check(models.ErrorResponse, missing.json())
    _check(models.ImageResponse, resized.json())
    _check(models.ImageLoadResponse, loaded.json())
    _check(models.ErrorResponse, local.json())
    _check(models.PingResponse, ping.json())
