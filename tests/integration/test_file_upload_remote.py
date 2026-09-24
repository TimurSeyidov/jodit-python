"""``fileUploadRemote`` against a real local HTTP server."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import TYPE_CHECKING, ClassVar

import pytest
from PIL import Image

from jcpy.config.loader import build_config
from jcpy.errors import HttpError
from jcpy.helpers import ssrf
from jcpy.services.remote_upload import upload_from_url
from jcpy.sources import SourcePool
from tests.conftest import (
    BASEURL,
    service_context,
    source_config,
    write_file,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from httpx import AsyncClient, Response

    from jcpy.types import JsonObject, JsonValue
    from tests.conftest import ClientFactory


def png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), "red").save(output, "PNG")
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    """Serves fixed test files."""

    files: ClassVar[dict[str, bytes]] = {
        "/test-image.png": png(),
        "/docs/report.pdf": b"%PDF-1.4",
        "/shell.php": b"<?php",
        "/my%20file.txt": b"spaced",
        "/big.txt": b"x" * 2048,
        "/big.php": b"x" * 2048,
        "/": b"root",
    }

    def do_GET(self) -> None:
        if self.path == "/redirect-image.png":
            self.send_response(302)
            self.send_header("Location", "/test-image.png")
            self.end_headers()
            return
        body = self.files.get(self.path.split("?", 1)[0])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Keep the test output quiet."""


@pytest.fixture(scope="module")
def remote() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "test"
    write_file(base, "keep.txt", "k")
    (base / "sub").mkdir()
    return base


def config(root: Path, **settings: JsonValue) -> JsonObject:
    return source_config(root, allowPrivateNetworkUploads=True, **settings)


async def upload(http: AsyncClient, url: str, **params: str) -> Response:
    return await http.get(
        "/",
        params={
            "action": "fileUploadRemote",
            "source": "test",
            "url": url,
            **params,
        },
    )


def messages(response: Response) -> list[str]:
    result: list[str] = response.json()["data"]["messages"]
    return result


async def test_uploads_an_image(
    connector_client: ClientFactory, root: Path, remote: str
) -> None:
    async with connector_client(config(root)) as http:
        response = await upload(http, f"{remote}/test-image.png?v=1")

    assert response.json() == {
        "success": True,
        "data": {
            "code": 220,
            "baseurl": BASEURL,
            "newfilename": "test-image.png",
            "isImage": True,
        },
    }
    assert (root / "test-image.png").read_bytes() == png()


async def test_name_and_directory(
    connector_client: ClientFactory, root: Path, remote: str
) -> None:
    async with connector_client(config(root)) as http:
        pdf = await upload(http, f"{remote}/docs/report.pdf", path="sub")
        spaced = await upload(http, f"{remote}/my%20file.txt")
        again = await upload(http, f"{remote}/my%20file.txt")

    assert pdf.json()["data"]["newfilename"] == "report.pdf"
    assert pdf.json()["data"]["isImage"] is False
    assert (root / "sub" / "report.pdf").exists()
    assert spaced.json()["data"]["newfilename"] == "my file.txt"
    assert again.json()["data"]["newfilename"] == "my file-1.txt"


async def test_follows_redirects(
    connector_client: ClientFactory, root: Path, remote: str
) -> None:
    async with connector_client(config(root)) as http:
        response = await upload(http, f"{remote}/redirect-image.png")

    assert response.json()["data"]["newfilename"] == "redirect-image.png"
    assert (root / "redirect-image.png").read_bytes() == png()


@pytest.mark.parametrize(
    ("path", "status", "message"),
    [
        ("/missing.png", 400, "File was not loaded: HTTP 404"),
        ("/shell.php", 403, "File type is not in white list"),
        ("/", 403, "File type is not in white list"),
        ("/big.txt", 403, "File size exceeds the allowable"),
        ("/big.php", 403, "File type is not in white list"),
    ],
)
async def test_refusals(
    connector_client: ClientFactory,
    root: Path,
    remote: str,
    path: str,
    status: int,
    message: str,
) -> None:
    async with connector_client(config(root, maxUploadFileSize="1kb")) as http:
        response = await upload(http, f"{remote}{path}")

    assert response.status_code == status
    assert messages(response) == [message]
    assert sorted(item.name for item in root.iterdir()) == ["keep.txt", "sub"]


@pytest.mark.parametrize(
    ("strategy", "status", "name"),
    [("replace", 200, "keep.txt"), ("error", 400, None)],
)
async def test_same_name_strategies(
    connector_client: ClientFactory,
    root: Path,
    remote: str,
    strategy: str,
    status: int,
    name: str | None,
) -> None:
    Handler.files["/keep.txt"] = b"remote"
    async with connector_client(
        config(root, saveSameFileNameStrategy=strategy)
    ) as http:
        response = await upload(http, f"{remote}/keep.txt")

    assert response.status_code == status
    if name:
        assert (root / name).read_bytes() == b"remote"
    else:
        assert messages(response) == ["File keep.txt already exists"]


async def test_extensionless_numbering(
    connector_client: ClientFactory, root: Path, remote: str
) -> None:
    write_file(root, "downloaded-file", "old")
    async with connector_client(
        config(root, extensions=[""], imageExtensions=[])
    ) as http:
        response = await upload(http, f"{remote}/")

    assert response.status_code == 403
    assert not (root / "downloaded-file-1").exists()


@pytest.mark.parametrize(
    ("url", "status", "message"),
    [
        ("http://127.0.0.1:1/a.png", 403, "private or local"),
        ("http://localhost/a.png", 403, "not allowed"),
        ("file:///etc/passwd", 400, "Only http and https"),
    ],
)
async def test_ssrf_protection_is_on_by_default(
    connector_client: ClientFactory,
    root: Path,
    url: str,
    status: int,
    message: str,
) -> None:
    async with connector_client(source_config(root)) as http:
        response = await upload(http, url)

    assert response.status_code == status
    assert message in messages(response)[0]


async def test_guarded_download_over_real_network(
    connector_client: ClientFactory,
    root: Path,
    remote: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssrf, "is_private_address", lambda address: False)
    async with connector_client(source_config(root)) as http:
        response = await upload(http, f"{remote}/test-image.png")

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("params", "status", "message"),
    [
        ({"url": ""}, 400, "Invalid URL"),
        ({"url": "not-a-valid-url"}, 400, "Invalid URL"),
        ({"source": "nope", "url": "http://x/a"}, 404, "Source not found"),
    ],
)
async def test_parameter_errors(
    connector_client: ClientFactory,
    root: Path,
    params: dict[str, str],
    status: int,
    message: str,
) -> None:
    async with connector_client(config(root)) as http:
        response = await http.get("/fileUploadRemote", params=params)

    assert response.status_code == status
    assert messages(response) == [message]


async def test_missing_url(
    connector_client: ClientFactory, root: Path
) -> None:
    async with connector_client(config(root)) as http:
        response = await http.get("/fileUploadRemote")

    assert messages(response) == [
        "Invalid input: expected string, received undefined"
    ]


async def test_access_control(
    connector_client: ClientFactory, root: Path, remote: str
) -> None:
    remote_denied: JsonValue = [{"role": "*", "FILE_UPLOAD_REMOTE": False}]
    upload_denied: JsonValue = [
        {"role": "*", "extensions": ["png"], "FILE_UPLOAD": False}
    ]
    async with connector_client(
        config(root, accessControl=remote_denied)
    ) as http:
        first = await upload(http, f"{remote}/test-image.png")
    async with connector_client(
        config(root, accessControl=upload_denied)
    ) as http:
        second = await upload(http, f"{remote}/test-image.png")

    assert first.status_code == 403
    assert second.status_code == 403
    assert not (root / "test-image.png").exists()


async def test_numbering_skips_taken_names(
    connector_client: ClientFactory, root: Path, remote: str
) -> None:
    write_file(root, "report.pdf", "a")
    write_file(root, "report-1.pdf", "b")
    async with connector_client(config(root)) as http:
        response = await upload(http, f"{remote}/docs/report.pdf")

    assert response.json()["data"]["newfilename"] == "report-2.pdf"


@pytest.mark.parametrize("fail_on_call", [1, 2])
async def test_existence_check_failures_count_as_free(
    root: Path,
    remote: str,
    monkeypatch: pytest.MonkeyPatch,
    fail_on_call: int,
) -> None:
    write_file(root, "report.pdf", "old")
    source = SourcePool(build_config(config(root)))._build()["test"]
    original = source.storage.file_exists
    calls: list[str] = []

    async def flaky(path: str) -> bool:
        calls.append(path)
        if len(calls) == fail_on_call:
            msg = "offline"
            raise OSError(msg)
        return await original(path)

    monkeypatch.setattr(source.storage, "file_exists", flaky)

    stored = await upload_from_url(
        service_context(), source, f"{remote}/docs/report.pdf", "/"
    )

    expected = "report.pdf" if fail_on_call == 1 else "report-1.pdf"
    assert stored.name == expected


async def test_invalid_url_in_service(root: Path) -> None:
    source = SourcePool(build_config(config(root)))._build()["test"]

    with pytest.raises(HttpError, match="Invalid URL"):
        await upload_from_url(service_context(), source, "nope", "/")
