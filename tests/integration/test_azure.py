"""Azure Blob adapter against Azurite in Docker (Testcontainers).

Skipped when no Docker daemon is reachable.
"""

import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from azure.core.exceptions import HttpResponseError
from azure.storage.blob import (
    BlobServiceClient,
    ContainerSasPermissions,
    generate_container_sas,
)
from testcontainers.core.container import DockerContainer

from jcpy.config.models import AzureOptions
from jcpy.storage.azure import AzureStorageAdapter, AzureStorageError
from tests.adapter_contract import AdapterContract
from tests.conftest import make_app, open_client
from tests.docker import docker_available

if TYPE_CHECKING:
    from collections.abc import Iterator

    from azure.storage.blob import ContainerClient

    from jcpy.types import JsonObject

IMAGE = os.environ.get(
    "AZURITE_IMAGE", "mcr.microsoft.com/azure-storage/azurite:latest"
)
ACCOUNT = "devstoreaccount1"
# Azurite's published development key, the same for every install.
KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw=="
)
CONTAINER = "jodit"

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not docker_available(), reason="Docker is not available"
    ),
]


@pytest.fixture(scope="module")
def blob_endpoint() -> Iterator[str]:
    container = (
        DockerContainer(IMAGE)
        .with_command(
            "azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck --loose"
        )
        .with_exposed_ports(10000)
    )
    with container:
        endpoint = (
            f"http://{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(10000)}/{ACCOUNT}"
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                BlobServiceClient.from_connection_string(
                    connection_string(endpoint)
                ).create_container(CONTAINER)
                break
            except Exception:  # Azurite still starting
                if time.monotonic() > deadline:
                    pytest.fail("Azurite did not start")
                time.sleep(0.5)
        yield endpoint


def connection_string(endpoint: str) -> str:
    return (
        f"DefaultEndpointsProtocol=http;AccountName={ACCOUNT};"
        f"AccountKey={KEY};BlobEndpoint={endpoint};"
    )


def options(endpoint: str, **values: object) -> AzureOptions:
    settings: dict[str, object] = {
        "container": CONTAINER,
        "connectionString": connection_string(endpoint),
        "prefix": f"test-{uuid.uuid4().hex[:8]}",
    }
    settings.update(values)
    return AzureOptions.model_validate(settings)


def container_client(endpoint: str) -> ContainerClient:
    return BlobServiceClient.from_connection_string(
        connection_string(endpoint)
    ).get_container_client(CONTAINER)


class TestAzurite(AdapterContract):
    @pytest.fixture
    def adapter(self, blob_endpoint: str) -> AzureStorageAdapter:
        return AzureStorageAdapter(options(blob_endpoint))


class TestCredentials:
    async def test_account_key(self, blob_endpoint: str) -> None:
        adapter = AzureStorageAdapter(
            options(
                blob_endpoint,
                connectionString=None,
                accountUrl=blob_endpoint,
                accountKey=KEY,
            )
        )

        await adapter.write("a.txt", b"key")

        assert await adapter.read("a.txt") == b"key"

    async def test_sas_token(self, blob_endpoint: str) -> None:
        token = generate_container_sas(
            ACCOUNT,
            CONTAINER,
            account_key=KEY,
            permission=ContainerSasPermissions(
                read=True, write=True, delete=True, list=True
            ),
            expiry=datetime.now(UTC) + timedelta(hours=1),
        )
        adapter = AzureStorageAdapter(
            options(
                blob_endpoint,
                connectionString=None,
                accountUrl=blob_endpoint,
                sasToken=token,
            )
        )

        # No copy here: Azurite answers 500 to a server-side copy of a
        # SAS-authorized source (the service itself accepts it).
        await adapter.write("a.txt", b"sas")

        assert await adapter.read("a.txt") == b"sas"
        assert [e.path async for e in adapter.list("", deep=False)] == [
            "a.txt"
        ]

    async def test_errors_hide_the_account_and_key(
        self, blob_endpoint: str
    ) -> None:
        wrong = KEY[:-4] + "AAA="
        adapter = AzureStorageAdapter(
            options(
                blob_endpoint,
                connectionString=None,
                accountUrl=blob_endpoint,
                accountKey=wrong,
                maxAttempts=1,
            )
        )

        with pytest.raises(AzureStorageError) as info:
            await adapter.stat("secret/a.txt")

        message = str(info.value)
        assert message.startswith("stat /secret/a.txt failed: 403")
        assert ACCOUNT not in message
        assert wrong not in message


class TestObjectOptions:
    async def test_cache_control_and_tier(self, blob_endpoint: str) -> None:
        settings = options(
            blob_endpoint, cacheControl="max-age=60", accessTier="Cool"
        )
        adapter = AzureStorageAdapter(settings)

        await adapter.write_file("a.png", BytesIO(b"png"))

        blob = container_client(blob_endpoint).get_blob_client(
            f"{settings.prefix}/a.png"
        )
        properties = blob.get_blob_properties()
        assert properties.content_settings.content_type == "image/png"
        assert properties.content_settings.cache_control == "max-age=60"
        assert properties.blob_tier == "Cool"

    async def test_copy_streams_when_the_service_cannot_read_the_source(
        self, blob_endpoint: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = AzureStorageAdapter(options(blob_endpoint))
        await adapter.write("a.bin", b"x" * 100)

        def refuse(*args: object, **kwargs: object) -> None:
            error = HttpResponseError(message="refused")
            code = "CannotVerifyCopySource"
            error.error_code = code  # type: ignore[attr-defined]
            raise error

        monkeypatch.setattr(
            "azure.storage.blob.BlobClient.start_copy_from_url", refuse
        )

        await adapter.copy_file("a.bin", "b.bin")

        assert await adapter.read("b.bin") == b"x" * 100


class TestConnector:
    async def test_upload_list_and_download(self, blob_endpoint: str) -> None:
        settings = options(blob_endpoint)
        config: JsonObject = {
            "sources": {
                "blob": {
                    "title": "Blob",
                    "baseurl": (
                        f"{blob_endpoint}/{CONTAINER}/{settings.prefix}/"
                    ),
                    "storageAdapter": "azure",
                    "azure": settings.model_dump(
                        by_alias=True, exclude_none=True
                    ),
                }
            }
        }

        async with open_client(make_app(config)) as http:
            uploaded = await http.post(
                "/fileUpload",
                data={"source": "blob", "path": "/"},
                files={"files[0]": ("note.txt", b"hello", "text/plain")},
            )
            listed = await http.post("/files", json={"source": "blob"})
            downloaded = await http.get(
                "/fileDownload", params={"source": "blob", "name": "note.txt"}
            )

        assert uploaded.status_code == 200, uploaded.text
        files = listed.json()["data"]["sources"][0]["files"]
        assert [item["file"] for item in files] == ["note.txt"]
        assert downloaded.content == b"hello"
