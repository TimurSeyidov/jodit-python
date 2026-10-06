"""The s3 adapter against other S3-compatible services in Docker.

OpenStack Swift with the s3api middleware and Ceph RADOS Gateway, the
object stores behind most OpenStack clouds. Both images are amd64
only (emulated on arm64 hosts); skipped without a Docker daemon.
"""

import os
import time
import uuid
from typing import TYPE_CHECKING

import boto3
import pytest
from botocore.config import Config
from testcontainers.core.container import DockerContainer

from jcpy.config.models import S3Options
from jcpy.storage.s3 import S3StorageAdapter
from tests.adapter_contract import AdapterContract
from tests.conftest import make_app, open_client
from tests.docker import docker_available

if TYPE_CHECKING:
    from collections.abc import Iterator

    from jcpy.types import JsonObject

SWIFT_IMAGE = os.environ.get("SWIFT_IMAGE", "openstackswift/saio:latest")
CEPH_IMAGE = os.environ.get("CEPH_IMAGE", "quay.io/ceph/demo:latest-squid")
BUCKET = "jodit"

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not docker_available(), reason="Docker is not available"
    ),
]


def wait_for_bucket(
    endpoint: str, key: str, secret: str, *, create: bool, what: str
) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    deadline = time.monotonic() + 240
    while True:
        try:
            if create:
                client.create_bucket(Bucket=BUCKET)
            else:
                client.head_bucket(Bucket=BUCKET)
            return
        except Exception:  # service still starting
            if time.monotonic() > deadline:
                pytest.fail(f"{what} did not start")
            time.sleep(2)


def service(
    container: DockerContainer,
    port: int,
    key: str,
    secret: str,
    *,
    create: bool,
    what: str,
) -> Iterator[dict[str, object]]:
    with container:
        host = container.get_container_host_ip()
        # The Ceph demo image sets "rgw dns name" to the container name
        # and then answers NoSuchBucket to Host: localhost; an IP works.
        if host == "localhost":
            host = "127.0.0.1"
        endpoint = f"http://{host}:{container.get_exposed_port(port)}"
        wait_for_bucket(endpoint, key, secret, create=create, what=what)
        yield {
            "bucket": BUCKET,
            "endpoint": endpoint,
            "forcePathStyle": True,
            "credentials": {"accessKeyId": key, "secretAccessKey": secret},
        }


@pytest.fixture(scope="module")
def swift() -> Iterator[dict[str, object]]:
    # tempauth user test:tester; s3api is in the proxy pipeline.
    container = DockerContainer(
        SWIFT_IMAGE, platform="linux/amd64"
    ).with_exposed_ports(8080)
    yield from service(
        container, 8080, "test:tester", "testing", create=True, what="Swift"
    )


@pytest.fixture(scope="module")
def ceph() -> Iterator[dict[str, object]]:
    container = (
        DockerContainer(CEPH_IMAGE, platform="linux/amd64")
        .with_env("MON_IP", "127.0.0.1")
        .with_env("CEPH_PUBLIC_NETWORK", "0.0.0.0/0")
        .with_env("CEPH_DEMO_UID", "demo")
        .with_env("CEPH_DEMO_ACCESS_KEY", "demokey")
        .with_env("CEPH_DEMO_SECRET_KEY", "demosecret")
        .with_env("RGW_FRONTEND_PORT", "8080")
        .with_env("DEMO_DAEMONS", "mon mgr osd rgw")
        .with_exposed_ports(8080)
    )
    yield from service(
        container, 8080, "demokey", "demosecret", create=True, what="Ceph"
    )


def adapter_for(settings: dict[str, object]) -> S3StorageAdapter:
    options = {**settings, "prefix": f"c-{uuid.uuid4().hex[:8]}"}
    return S3StorageAdapter(S3Options.model_validate(options))


class TestSwift(AdapterContract):
    @pytest.fixture
    def adapter(self, swift: dict[str, object]) -> S3StorageAdapter:
        return adapter_for(swift)


class TestCeph(AdapterContract):
    @pytest.fixture
    def adapter(self, ceph: dict[str, object]) -> S3StorageAdapter:
        return adapter_for(ceph)


@pytest.mark.parametrize("name", ["swift", "ceph"])
async def test_connector(name: str, request: pytest.FixtureRequest) -> None:
    settings: JsonObject = {
        **request.getfixturevalue(name),
        "prefix": f"c-{uuid.uuid4().hex[:8]}",
    }
    config: JsonObject = {
        "sources": {
            "bucket": {
                "title": "Bucket",
                "baseurl": "https://files.example.com/",
                "storageAdapter": "s3",
                "s3": settings,
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
            "/fileDownload", params={"source": "bucket", "name": "note.txt"}
        )

    assert uploaded.status_code == 200, uploaded.text
    files = listed.json()["data"]["sources"][0]["files"]
    assert [item["file"] for item in files] == ["note.txt"]
    assert downloaded.content == b"hello"
