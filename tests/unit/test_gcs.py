"""GCS adapter against gcp-storage-emulator in the test process."""

import json
import logging
import uuid
from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from gcp_storage_emulator.server import create_server
from google.api_core.exceptions import Forbidden
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from pydantic import ValidationError

from jcpy.config.models import GcsOptions
from jcpy.storage.gcs import GcsStorageAdapter, GcsStorageError, create_client
from tests.adapter_contract import AdapterContract

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

BUCKET = "jodit"


@pytest.fixture(scope="module")
def endpoint() -> Iterator[str]:
    logging.getLogger("gcp_storage_emulator").setLevel(logging.WARNING)
    server = create_server(
        "127.0.0.1", 0, in_memory=True, default_bucket=BUCKET
    )
    server.start()
    try:
        host, port = server._api._httpd.server_address
        yield f"http://{host}:{port}"
    finally:
        server.stop()


def options(endpoint: str, **values: object) -> GcsOptions:
    settings: dict[str, object] = {
        "bucket": BUCKET,
        "endpoint": endpoint,
        "anonymous": True,
        "prefix": f"test-{uuid.uuid4().hex[:8]}",
    }
    settings.update(values)
    return GcsOptions.model_validate(settings)


class TestEmulator(AdapterContract):
    @pytest.fixture
    def adapter(self, endpoint: str) -> GcsStorageAdapter:
        return GcsStorageAdapter(options(endpoint))


class TestClient:
    def test_anonymous(self) -> None:
        client = create_client(
            GcsOptions.model_validate(
                {
                    "bucket": BUCKET,
                    "anonymous": True,
                    "endpoint": "http://127.0.0.1:1",
                }
            )
        )

        assert isinstance(client._credentials, AnonymousCredentials)
        assert client.project == "<none>"

    def test_service_account_file(self, tmp_path: Path) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        path = tmp_path / "key.json"
        path.write_text(
            json.dumps(
                {
                    "type": "service_account",
                    "project_id": "demo-project",
                    "private_key_id": "1",
                    "private_key": pem,
                    "client_email": (
                        "editor@demo-project.iam.gserviceaccount.com"
                    ),
                    "client_id": "1",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
        )

        client = create_client(
            GcsOptions.model_validate(
                {"bucket": BUCKET, "credentialsFile": str(path)}
            )
        )

        assert client.project == "demo-project"
        assert client._credentials.service_account_email.startswith("editor@")

    def test_application_default_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        credentials = AnonymousCredentials()
        monkeypatch.setattr(
            "google.auth.default",
            lambda **kwargs: (credentials, "adc-project"),
        )

        client = create_client(
            GcsOptions.model_validate({"bucket": BUCKET, "project": "p"})
        )

        assert client._credentials is credentials
        assert client.project == "p"

    @pytest.mark.parametrize(
        ("values", "message"),
        [
            ({"anonymous": True, "credentialsFile": "k.json"}, "not both"),
            ({"storageClass": "GLACIER"}, "STANDARD"),
            ({"endpoint": "not a url"}, "URL"),
        ],
    )
    def test_invalid_options(
        self, values: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValidationError, match=message):
            GcsOptions.model_validate({"bucket": BUCKET, **values})


class TestAdapterDetails:
    def test_public_url(self, endpoint: str) -> None:
        adapter = GcsStorageAdapter(options(endpoint, prefix="media"))
        custom = GcsStorageAdapter(
            options(endpoint, publicBaseUrl="https://cdn.example.com/")
        )

        base = f"https://storage.googleapis.com/{BUCKET}/media"
        assert adapter.public_url("") == base
        assert adapter.public_url("/a/b.png") == f"{base}/a/b.png"
        assert custom.public_url("a.png") == "https://cdn.example.com/a.png"

    def test_error_message(self) -> None:
        error = Forbidden(
            "GET https://storage.googleapis.com/storage/v1/b/secret: denied",
            errors=[{"reason": "forbidden", "message": "denied"}],
        )

        message = str(GcsStorageError("read", "a.txt", error))

        assert message == "read /a.txt failed: 403 forbidden"
        assert "googleapis" not in message

    async def test_copy_sets_the_storage_class(
        self, endpoint: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The emulators ignore the class of a rewrite; check the request.
        adapter = GcsStorageAdapter(options(endpoint, storageClass="COLDLINE"))
        await adapter.write("a.txt", b"a")
        sent: list[str | None] = []

        def rewrite(
            self: storage.Blob, source: storage.Blob, **kwargs: object
        ) -> tuple[None, int, int]:
            sent.append(self.storage_class)
            return None, 1, 1

        monkeypatch.setattr(storage.Blob, "rewrite", rewrite)

        await adapter.copy_file("a.txt", "b.txt")

        assert sent == ["COLDLINE"]

    async def test_long_copies_continue_with_the_token(
        self, endpoint: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = GcsStorageAdapter(options(endpoint))
        await adapter.write("a.txt", b"a")
        tokens: list[str | None] = []
        answers = iter([("t1", 1, 3), ("t2", 2, 3), (None, 3, 3)])

        def rewrite(
            self: storage.Blob,
            source: storage.Blob,
            token: str | None = None,
            **kwargs: object,
        ) -> tuple[str | None, int, int]:
            tokens.append(token)
            return next(answers)

        monkeypatch.setattr(storage.Blob, "rewrite", rewrite)

        await adapter.copy_file("a.txt", "b.txt")

        assert tokens == [None, "t1", "t2"]

    async def test_copying_a_missing_object(self, endpoint: str) -> None:
        adapter = GcsStorageAdapter(options(endpoint))

        with pytest.raises(FileNotFoundError):
            await adapter.copy_file("missing.txt", "b.txt")

    async def test_bucket_root_without_prefix(self, endpoint: str) -> None:
        name = f"bare-{uuid.uuid4().hex[:8]}"
        storage.Client(
            project="test",
            credentials=AnonymousCredentials(),
            client_options={"api_endpoint": endpoint},
        ).create_bucket(name)
        adapter = GcsStorageAdapter(options(endpoint, bucket=name, prefix=""))

        await adapter.create_directory("")
        await adapter.write("dir/a.txt", b"a")

        assert not await adapter.file_exists("")
        assert [e.path async for e in adapter.list("", deep=False)] == ["dir"]

    async def test_other_service_errors(
        self, endpoint: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = GcsStorageAdapter(options(endpoint))

        def refuse(*args: object, **kwargs: object) -> None:
            raise Forbidden("denied", errors=[{"reason": "forbidden"}])

        monkeypatch.setattr(storage.Blob, "download_as_bytes", refuse)

        with pytest.raises(GcsStorageError, match="403 forbidden"):
            await adapter.read("a.txt")

    async def test_missing_bucket_is_an_error(self, endpoint: str) -> None:
        adapter = GcsStorageAdapter(options(endpoint, bucket="no-such"))

        with pytest.raises(GcsStorageError, match="404"):
            await adapter.stat("a.txt")
