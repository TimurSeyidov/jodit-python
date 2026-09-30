"""Google Cloud Storage adapter against fake-gcs-server in Docker.

The adapter contract runs against gcp-storage-emulator in the unit
tests (fake-gcs-server drops folder markers); this covers resumable
uploads, errors and the connector. Skipped without a Docker daemon.
"""

import os
import re
import time
import uuid
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from testcontainers.core.container import DockerContainer

from jcpy.config.models import GcsOptions
from jcpy.storage.gcs import GcsStorageAdapter, GcsStorageError
from tests.conftest import make_app, open_client
from tests.docker import docker_available

if TYPE_CHECKING:
    from collections.abc import Iterator

    from jcpy.types import JsonObject

IMAGE = os.environ.get("GCS_IMAGE", "fsouza/fake-gcs-server:latest")
BUCKET = "jodit"

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not docker_available(), reason="Docker is not available"
    ),
]


def client(endpoint: str) -> storage.Client:
    return storage.Client(
        project="test",
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": endpoint},
    )


@pytest.fixture(scope="module")
def endpoint() -> Iterator[str]:
    container = (
        DockerContainer(IMAGE)
        .with_command("-scheme http -port 4443")
        .with_exposed_ports(4443)
    )
    with container:
        url = (
            f"http://{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(4443)}"
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                client(url).create_bucket(BUCKET)
                break
            except Exception:  # fake-gcs-server still starting
                if time.monotonic() > deadline:
                    pytest.fail("fake-gcs-server did not start")
                time.sleep(0.5)
        yield url


def options(endpoint: str, **values: object) -> GcsOptions:
    settings: dict[str, object] = {
        "bucket": BUCKET,
        "endpoint": endpoint,
        "anonymous": True,
        "prefix": f"test-{uuid.uuid4().hex[:8]}",
    }
    settings.update(values)
    return GcsOptions.model_validate(settings)


class TestObjectOptions:
    async def test_options_and_metadata_survive_copies(
        self, endpoint: str
    ) -> None:
        settings = options(
            endpoint, cacheControl="max-age=60", storageClass="NEARLINE"
        )
        adapter = GcsStorageAdapter(settings)

        await adapter.write_file("a.png", BytesIO(b"png"))
        await adapter.copy_file("a.png", "b.png")

        bucket = client(endpoint).bucket(BUCKET)
        for name in ("a.png", "b.png"):
            blob = bucket.get_blob(f"{settings.prefix}/{name}")
            assert blob is not None
            assert blob.content_type == "image/png"
            assert blob.cache_control == "max-age=60"
        # The emulator keeps the class of uploads only, not of rewrites.
        uploaded = bucket.get_blob(f"{settings.prefix}/a.png")
        assert uploaded is not None
        assert uploaded.storage_class == "NEARLINE"

    async def test_large_uploads_go_in_parts(
        self, endpoint: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("jcpy.storage.gcs.PART_SIZE", 256 * 1024)
        adapter = GcsStorageAdapter(options(endpoint))
        body = os.urandom(700 * 1024)

        await adapter.write_file("big.bin", BytesIO(body))

        assert await adapter.read("big.bin") == body
        chunks = [chunk async for chunk in adapter.iter_file("big.bin")]
        assert b"".join(chunks) == body


class TestErrors:
    async def test_errors_hide_the_endpoint(self, endpoint: str) -> None:
        adapter = GcsStorageAdapter(options(endpoint, bucket="missing-bkt"))

        with pytest.raises(GcsStorageError) as info:
            await adapter.write("secret/a.txt", b"x")

        message = str(info.value)
        assert re.match(r"\w+ /secret/a\.txt failed: 404", message)
        assert endpoint not in message
        assert "missing-bkt" not in message


class TestConnector:
    async def test_upload_list_and_download(self, endpoint: str) -> None:
        settings = options(endpoint)
        config: JsonObject = {
            "sources": {
                "bucket": {
                    "title": "Bucket",
                    "baseurl": (
                        f"https://storage.googleapis.com/{BUCKET}/"
                        f"{settings.prefix}/"
                    ),
                    "storageAdapter": "gcs",
                    "gcs": settings.model_dump(
                        by_alias=True, exclude_none=True
                    ),
                }
            }
        }

        async with open_client(make_app(config)) as http:
            uploaded = await http.post(
                "/fileUpload",
                data={"source": "bucket", "path": "/"},
                files={"files[0]": ("note.txt", b"hello", "text/plain")},
            )
            listed = await http.post("/files", json={"source": "bucket"})
            downloaded = await http.get(
                "/fileDownload",
                params={"source": "bucket", "name": "note.txt"},
            )

        assert uploaded.status_code == 200, uploaded.text
        files = listed.json()["data"]["sources"][0]["files"]
        assert [item["file"] for item in files] == ["note.txt"]
        assert downloaded.content == b"hello"
