"""Azure adapter parts that need no service: options, errors, fakes."""

from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from azure.core.exceptions import (
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.storage.blob import ContainerClient
from pydantic import ValidationError

from jcpy.config.models import AzureOptions
from jcpy.storage import azure as azure_module
from jcpy.storage.azure import (
    AzureStorageAdapter,
    AzureStorageError,
    _FullReader,
    account_name,
    batch_requests_work,
    create_container_client,
)

URL = "https://acct.blob.core.windows.net"


def options(**values: object) -> AzureOptions:
    return AzureOptions.model_validate(
        {"container": "files", "accountUrl": URL, **values}
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (URL, "acct"),
        ("https://acct.blob.core.windows.net/", "acct"),
        ("http://127.0.0.1:10000/devstoreaccount1", "devstoreaccount1"),
    ],
)
def test_account_name(url: str, expected: str) -> None:
    assert account_name(url) == expected


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"accountUrl": None}, "one of them"),
        ({"connectionString": "x"}, "one of them"),
        (
            {"accountUrl": None, "connectionString": "x", "sasToken": "s"},
            "go with accountUrl",
        ),
        ({"accountKey": "k", "sasToken": "s"}, "not both"),
        ({"accountUrl": "not a url"}, "URL"),
        ({"accessTier": "Archive"}, "Hot"),
    ],
)
def test_invalid_options(values: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        options(**values)


def test_default_credential_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    class Credential:
        def get_token(self, *scopes: str, **kwargs: object) -> None:
            raise NotImplementedError

    marker = Credential()
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential", lambda: marker
    )

    client = create_container_client(options())

    assert client.credential is marker
    assert client.url == f"{URL}/files"


def test_account_key_credential() -> None:
    client = create_container_client(options(accountKey="a2V5"))

    assert client.credential.account_name == "acct"


def test_public_url() -> None:
    adapter = AzureStorageAdapter(options(prefix="media"))
    custom = AzureStorageAdapter(
        options(publicBaseUrl="https://cdn.example.com/files/")
    )

    assert adapter.public_url("") == f"{URL}/files/media"
    assert adapter.public_url("/a/b.png") == f"{URL}/files/media/a/b.png"
    assert custom.public_url("a.png") == "https://cdn.example.com/files/a.png"


def test_error_message_keeps_urls_out() -> None:
    error = HttpResponseError(
        message=f"Server failed: {URL}/files/a?sig=SECRET"
    )
    error.status_code = 403
    error.error_code = "AuthorizationFailure"  # type: ignore[attr-defined]
    silent = ServiceRequestError(f"cannot reach {URL}")

    assert str(AzureStorageError("read", "a", error)) == (
        "read /a failed: 403 AuthorizationFailure"
    )
    assert str(AzureStorageError("read", "a", silent)) == (
        "read /a failed: ServiceRequestError"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{URL}/files", True),
        ("http://127.0.0.1:10000/devstoreaccount1/files", True),
        ("http://localhost:10000/devstoreaccount1/files", True),
        ("http://azurite:10000/devstoreaccount1/files", False),
    ],
)
def test_batch_requests_work(url: str, expected: bool) -> None:
    base, container = url.rsplit("/", 1)
    client = ContainerClient(base, container)

    assert batch_requests_work(client) is expected


class TestFullReader:
    def test_completes_short_reads(self) -> None:
        class Trickle(BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                return super().read(min(size or 1, 2) if size != -1 else -1)

        reader = _FullReader(Trickle(b"abcdefg"))

        assert reader.read(5) == b"abcde"
        assert reader.read(-1) == b"fg"
        assert reader.read(3) == b""


class FakeBlob:
    def __init__(self, container: FakeContainer, name: str) -> None:
        self.container = container
        self.name = name
        self.url = f"{URL}/files/{name}"

    def start_copy_from_url(self, source_url: str, **kwargs: object) -> None:
        if self.container.copy_error is not None:
            raise self.container.copy_error

    def get_blob_properties(self) -> SimpleNamespace:
        status = self.container.copy_states.pop(0)
        return SimpleNamespace(copy=SimpleNamespace(status=status))


class FakeContainer:
    url = f"{URL}/files"

    def __init__(self) -> None:
        self.copy_error: Exception | None = None
        self.copy_states: list[str | None] = []
        self.delete_statuses: list[int] = []
        self.blobs: list[str] = []
        self.deleted: list[str] = []

    def get_blob_client(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def list_blobs(self, **kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name) for name in self.blobs]

    def delete_blob(self, name: str) -> None:
        if name.endswith("gone"):
            raise ResourceNotFoundError("gone")
        self.deleted.append(name)

    def delete_blobs(self, *names: str, **kwargs: object) -> list[Any]:
        return [
            SimpleNamespace(status_code=code) for code in self.delete_statuses
        ]


@pytest.fixture
def fake() -> FakeContainer:
    return FakeContainer()


@pytest.fixture
def adapter(fake: FakeContainer) -> AzureStorageAdapter:
    return AzureStorageAdapter(options(), client=fake)  # type: ignore[arg-type]


class TestWithFakeService:
    async def test_pending_copy_is_awaited(
        self,
        adapter: AzureStorageAdapter,
        fake: FakeContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(azure_module, "COPY_POLL_SECONDS", 0)
        monkeypatch.setattr(adapter, "_refuse_directory", _nothing)
        fake.copy_states = ["pending", "pending", "success"]

        await adapter.copy_file("a", "b")

        assert fake.copy_states == []

    async def test_failed_copy(
        self,
        adapter: AzureStorageAdapter,
        fake: FakeContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(adapter, "_refuse_directory", _nothing)
        fake.copy_states = ["aborted"]

        with pytest.raises(OSError, match="status aborted"):
            await adapter.copy_file("a", "b")

    async def test_copy_errors(
        self,
        adapter: AzureStorageAdapter,
        fake: FakeContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(adapter, "_refuse_directory", _nothing)
        fake.copy_error = ResourceNotFoundError("gone")

        with pytest.raises(FileNotFoundError):
            await adapter.copy_file("a", "b")

        refused = HttpResponseError(message="quota")
        refused.error_code = "QuotaExceeded"  # type: ignore[attr-defined]
        fake.copy_error = refused
        with pytest.raises(AzureStorageError, match="QuotaExceeded"):
            await adapter.copy_file("a", "b")

    async def test_blob_by_blob_deletes(
        self,
        adapter: AzureStorageAdapter,
        fake: FakeContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(adapter, "file_exists", _false)
        adapter._batches = False
        fake.blobs = ["dir/a", "dir/gone", "dir/b"]

        await adapter.delete_directory("dir")

        assert fake.deleted == ["dir/a", "dir/b"]

    async def test_undeletable_blobs(
        self,
        adapter: AzureStorageAdapter,
        fake: FakeContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(adapter, "file_exists", _false)
        fake.blobs = ["dir/a", "dir/b", "dir/c"]
        fake.delete_statuses = [202, 404, 409]

        with pytest.raises(OSError, match="1 blob"):
            await adapter.delete_directory("dir")

    async def test_root_is_neither_created_nor_a_file(
        self, adapter: AzureStorageAdapter
    ) -> None:
        await adapter.create_directory("")

        assert not await adapter.file_exists("/")


async def _nothing(path: str) -> None:
    return None


async def _false(path: str) -> bool:
    return False
