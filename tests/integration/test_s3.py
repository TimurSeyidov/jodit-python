"""S3 adapter against MinIO in Docker (Testcontainers).

Ported from jodit-nodejs s3-storage-adapter.test.ts; skipped when no
Docker daemon is reachable.
"""

import os
import shutil
import subprocess
import time
from io import BytesIO
from typing import TYPE_CHECKING

import boto3
import httpx
import pytest
from PIL import Image
from testcontainers.core.container import DockerContainer

from jcpy.config.models import S3Options
from jcpy.storage import FileStorage
from jcpy.storage.s3 import S3StorageAdapter
from tests.conftest import make_app, open_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from httpx import AsyncClient
    from mypy_boto3_s3.client import S3Client

    from jcpy.types import JsonObject

BUCKET = "jodit"
PREFIX = "media"
USER = "minioadmin"
PASSWORD = "minioadmin"  # noqa: S105 - MinIO test default
# MinIO no longer publishes free images on quay.io or Docker Hub;
# Chainguard builds the same server. MINIO_IMAGE overrides it.
IMAGE = os.environ.get("MINIO_IMAGE", "cgr.dev/chainguard/minio:latest")


def docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [docker, "info"], capture_output=True, check=False
    )
    return result.returncode == 0


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not docker_available(), reason="Docker is not available"
    ),
]


@pytest.fixture(scope="module")
def minio() -> Iterator[str]:
    container = (
        DockerContainer(IMAGE)
        .with_env("MINIO_ROOT_USER", USER)
        .with_env("MINIO_ROOT_PASSWORD", PASSWORD)
        .with_command("server /data")
        .with_exposed_ports(9000)
    )
    with container:
        host = container.get_container_host_ip()
        endpoint = f"http://{host}:{container.get_exposed_port(9000)}"
        deadline = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"{endpoint}/minio/health/live").is_success:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("MinIO did not start")
            time.sleep(0.5)
        yield endpoint


def s3_settings(endpoint: str) -> JsonObject:
    return {
        "bucket": BUCKET,
        "endpoint": endpoint,
        "forcePathStyle": True,
        "prefix": PREFIX,
        "credentials": {"accessKeyId": USER, "secretAccessKey": PASSWORD},
    }


@pytest.fixture
def client(minio: str) -> Iterator[S3Client]:
    s3 = boto3.client(
        "s3",
        endpoint_url=minio,
        aws_access_key_id=USER,
        aws_secret_access_key=PASSWORD,
        region_name="us-east-1",
    )
    s3.create_bucket(Bucket=BUCKET)
    yield s3
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for item in page.get("Contents", []):
            s3.delete_object(Bucket=BUCKET, Key=item["Key"])
    s3.delete_bucket(Bucket=BUCKET)


@pytest.fixture
async def storage(minio: str, client: S3Client) -> FileStorage:
    adapter = S3StorageAdapter(S3Options.model_validate(s3_settings(minio)))
    storage = FileStorage(adapter)
    await storage.write("hello.txt", b"Hello S3")
    await storage.write("sub/nested.txt", b"Nested")
    await storage.create_directory("empty")
    client.put_object(Bucket=BUCKET, Key="other/secret.txt", Body=b"secret")
    return storage


def keys(client: S3Client, prefix: str = "") -> list[str]:
    page = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return sorted(item["Key"] for item in page.get("Contents", []))


async def listing(storage: FileStorage, path: str, *, deep: bool) -> set[str]:
    return {
        f"{entry.type}:{entry.path}"
        async for entry in storage.list(path, deep=deep)
    }


class TestAdapter:
    async def test_read_write(self, storage: FileStorage) -> None:
        assert await storage.read("hello.txt") == b"Hello S3"
        assert await storage.read("/sub/nested.txt") == b"Nested"

    async def test_stat(self, storage: FileStorage) -> None:
        file = await storage.stat("hello.txt")
        explicit = await storage.stat("empty")
        implicit = await storage.stat("sub")
        root = await storage.stat("")

        assert (file.is_file, file.size) == (True, 8)
        assert file.last_modified_ms
        assert explicit.is_directory
        assert implicit.is_directory
        assert root.is_directory
        with pytest.raises(Exception, match="Path not found"):
            await storage.stat("missing")

    async def test_exists(self, storage: FileStorage) -> None:
        assert await storage.file_exists("hello.txt")
        assert not await storage.file_exists("sub")
        assert not await storage.file_exists("")
        assert await storage.directory_exists("sub")
        assert await storage.directory_exists("empty")
        assert await storage.directory_exists("")
        assert not await storage.directory_exists("missing")

    async def test_listing(self, storage: FileStorage) -> None:
        assert await listing(storage, "", deep=False) == {
            "file:hello.txt",
            "directory:sub",
            "directory:empty",
        }
        await storage.write("sub/deep/x.txt", b"x")
        assert await listing(storage, "", deep=True) == {
            "file:hello.txt",
            "directory:sub",
            "directory:empty",
            "file:sub/nested.txt",
            "directory:sub/deep",
            "file:sub/deep/x.txt",
        }

    async def test_copy_move_delete(
        self, storage: FileStorage, client: S3Client
    ) -> None:
        await storage.copy_file("hello.txt", "copy of hello.txt")
        await storage.move_file("copy of hello.txt", "sub/moved.txt")
        await storage.delete_file("hello.txt")

        assert keys(client, PREFIX) == [
            "media/empty/",
            "media/sub/moved.txt",
            "media/sub/nested.txt",
        ]

    async def test_move_and_delete_folders(
        self, storage: FileStorage, client: S3Client
    ) -> None:
        await storage.write("sub/deep/x.txt", b"x")
        await storage.move_file("sub", "renamed")

        assert keys(client, f"{PREFIX}/renamed") == [
            "media/renamed/",
            "media/renamed/deep/",
            "media/renamed/deep/x.txt",
            "media/renamed/nested.txt",
        ]
        assert keys(client, f"{PREFIX}/sub") == []

        await storage.delete_directory("renamed")
        assert keys(client, f"{PREFIX}/renamed") == []
        with pytest.raises(Exception, match="Path not found"):
            await storage.move_file("nowhere", "x")

    async def test_content_type(
        self, storage: FileStorage, client: S3Client
    ) -> None:
        await storage.write("picture.png", b"png")

        head = client.head_object(Bucket=BUCKET, Key="media/picture.png")
        assert head["ContentType"] == "image/png"


def png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (300, 200), "blue").save(output, "PNG")
    return output.getvalue()


@pytest.fixture
async def http(minio: str, storage: FileStorage) -> AsyncIterator[AsyncClient]:
    config: JsonObject = {
        "sources": {
            "s3": {
                "title": "S3 bucket",
                "baseurl": f"{minio}/{BUCKET}/{PREFIX}/",
                "storageAdapter": "s3",
                "s3": s3_settings(minio),
            }
        }
    }
    async with open_client(make_app(config)) as client:
        yield client


async def names(http: AsyncClient, path: str = "/") -> list[str]:
    response = await http.post(
        "/files",
        json={"source": "s3", "path": path, "mods": {"withFolders": True}},
    )
    assert response.status_code == 200, response.text
    return sorted(
        item["name"] for item in response.json()["data"]["sources"][0]["files"]
    )


class TestConnector:
    async def test_listing_hides_objects_outside_the_prefix(
        self, http: AsyncClient
    ) -> None:
        assert await names(http) == ["empty", "hello.txt", "sub"]
        assert await names(http, "sub") == ["nested.txt"]

    async def test_folders(self, http: AsyncClient) -> None:
        response = await http.get("/folders", params={"source": "s3"})

        folders = response.json()["data"]["sources"][0]["folders"]
        assert folders[0] == "."
        assert sorted(folders[1:]) == ["empty", "sub"]

    async def test_folder_create(
        self, http: AsyncClient, client: S3Client
    ) -> None:
        response = await http.get(
            "/folderCreate", params={"source": "s3", "name": "fresh"}
        )

        assert response.status_code == 200
        assert "media/fresh/" in keys(client, PREFIX)

    async def test_upload_with_thumbnail(
        self, http: AsyncClient, client: S3Client
    ) -> None:
        response = await http.post(
            "/fileUpload",
            data={"source": "s3"},
            files=[("files[0]", ("pic.png", png(), "image/png"))],
        )
        await names(http)

        assert response.json()["data"]["files"] == ["pic.png"]
        assert {"media/pic.png", "media/_thumbs/pic.png"} <= set(
            keys(client, PREFIX)
        )

    async def test_resize_into_new_object(
        self, http: AsyncClient, client: S3Client
    ) -> None:
        await http.post(
            "/fileUpload",
            data={"source": "s3"},
            files=[("files[0]", ("pic.png", png(), "image/png"))],
        )
        response = await http.get(
            "/imageResize",
            params={
                "source": "s3",
                "name": "pic.png",
                "newname": "small.png",
                "box[w]": "30",
                "box[h]": "20",
            },
        )

        assert response.status_code == 200
        body = client.get_object(Bucket=BUCKET, Key="media/small.png")
        with Image.open(BytesIO(body["Body"].read())) as image:
            assert image.size == (30, 20)

    async def test_local_file_by_url(
        self, http: AsyncClient, minio: str
    ) -> None:
        response = await http.get(
            "/getLocalFileByUrl",
            params={"url": f"{minio}/{BUCKET}/{PREFIX}/sub/nested.txt"},
        )

        assert response.json()["data"] == {
            "code": 220,
            "path": "/sub",
            "name": "nested.txt",
            "source": "s3",
        }

    async def test_download(self, http: AsyncClient) -> None:
        response = await http.get(
            "/fileDownload", params={"source": "s3", "name": "hello.txt"}
        )

        assert response.content == b"Hello S3"

    async def test_rename_move_remove(
        self, http: AsyncClient, client: S3Client
    ) -> None:
        await http.get(
            "/fileRename",
            params={"source": "s3", "name": "hello.txt", "newname": "hi"},
        )
        await http.get(
            "/fileMove",
            params={"source": "s3", "from": "hi.txt", "path": "sub"},
        )
        await http.get(
            "/fileRemove",
            params={"source": "s3", "path": "sub", "name": "nested.txt"},
        )

        assert keys(client, PREFIX) == ["media/empty/", "media/sub/hi.txt"]

    async def test_folder_remove(
        self, http: AsyncClient, client: S3Client
    ) -> None:
        response = await http.get(
            "/folderRemove", params={"source": "s3", "name": "sub"}
        )

        assert response.status_code == 200
        assert keys(client, f"{PREFIX}/sub") == []

    async def test_traversal_is_clamped_to_the_virtual_root(
        self, http: AsyncClient
    ) -> None:
        missing = await http.get(
            "/files", params={"source": "s3", "path": "/../../other"}
        )

        assert missing.status_code == 404
        assert "other" not in await names(http, "/../..")
