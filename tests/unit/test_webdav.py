"""WebDAV adapter against an in-process WsgiDAV server."""

import uuid
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import ValidationError

from jcpy.config.models import WebdavOptions
from jcpy.storage.webdav import (
    DavEntry,
    WebdavError,
    WebdavStorageAdapter,
    parse_multistatus,
)
from tests.adapter_contract import AdapterContract
from tests.webdav_server import PASSWORD, TOKEN, USER, serving

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path


@pytest.fixture(scope="module")
def dav_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("dav")


@pytest.fixture(scope="module")
def dav_url(dav_root: Path) -> Iterator[str]:
    with serving(dav_root) as url:
        yield url


def make_adapter(
    url: str, root: Path, **values: object
) -> WebdavStorageAdapter:
    directory = f"folder {uuid.uuid4().hex[:8]}"
    (root / directory).mkdir()
    credentials = {"username": USER, "password": PASSWORD}
    options = WebdavOptions.model_validate(
        {"url": f"{url}{directory}", **credentials, **values}
    )
    return WebdavStorageAdapter(options)


class TestWsgiDav(AdapterContract):
    @pytest.fixture
    async def adapter(
        self, dav_url: str, dav_root: Path
    ) -> AsyncIterator[WebdavStorageAdapter]:
        adapter = make_adapter(dav_url, dav_root)
        yield adapter
        await adapter.aclose()


class TestAuthentication:
    async def test_wrong_password(self, dav_url: str, dav_root: Path) -> None:
        adapter = make_adapter(dav_url, dav_root, password="wrong")

        with pytest.raises(WebdavError, match="401"):
            await adapter.stat("")
        await adapter.aclose()

    async def test_digest(self, dav_root: Path) -> None:
        with serving(dav_root, digest=True) as url:
            adapter = make_adapter(url, dav_root, auth="digest")

            await adapter.write("a.txt", b"a")

            assert await adapter.read("a.txt") == b"a"
            await adapter.aclose()

    async def test_token(self, dav_url: str, dav_root: Path) -> None:
        options = WebdavOptions.model_validate(
            {"url": dav_url, "token": TOKEN}
        )
        adapter = WebdavStorageAdapter(options)

        assert (await adapter.stat("")).is_directory
        await adapter.aclose()

    def test_one_login(self) -> None:
        with pytest.raises(ValidationError, match="not both"):
            WebdavOptions.model_validate(
                {"url": "https://h/", "username": "u", "token": "t"}
            )

    @pytest.mark.parametrize("url", ["ftp://h/", "h/dav", "https://"])
    def test_url_must_be_http(self, url: str) -> None:
        with pytest.raises(ValidationError):
            WebdavOptions.model_validate({"url": url})


class TestErrors:
    async def test_errors_name_the_path_not_the_server(
        self, dav_url: str, dav_root: Path
    ) -> None:
        adapter = make_adapter(dav_url, dav_root, password="wrong")

        with pytest.raises(WebdavError) as info:
            await adapter.read("secret/a.txt")

        assert str(info.value).startswith("GET /secret/a.txt failed: 401")
        assert "127.0.0.1" not in str(info.value)
        await adapter.aclose()

    async def test_propfind_must_answer_multistatus(
        self, dav_url: str, dav_root: Path
    ) -> None:
        adapter = make_adapter(dav_url, dav_root)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html/>")

        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        with pytest.raises(WebdavError, match="PROPFIND /a failed: 200"):
            await adapter.stat("a")
        await adapter.aclose()

    async def test_aclose_is_idempotent(
        self, dav_url: str, dav_root: Path
    ) -> None:
        adapter = make_adapter(dav_url, dav_root)

        await adapter.aclose()
        await adapter.aclose()


def multistatus(*resources: tuple[str, bool]) -> str:
    responses = "".join(
        f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
        + (
            "<d:resourcetype><d:collection/></d:resourcetype>"
            if collection
            else "<d:resourcetype/><d:getcontentlength>1</d:getcontentlength>"
        )
        + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        "</d:response>"
        for href, collection in resources
    )
    return f'<d:multistatus xmlns:d="DAV:">{responses}</d:multistatus>'


def mocked(
    answers: dict[tuple[str, str], httpx.Response],
) -> tuple[WebdavStorageAdapter, list[tuple[str, str]]]:
    """Adapter whose server answers ``(method, path)`` from ``answers``."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        seen.append(key)
        return answers.get(key, httpx.Response(404))

    adapter = WebdavStorageAdapter(
        WebdavOptions.model_validate({"url": "https://files.example.com/dav"})
    )
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter, seen


ROOT = ("PROPFIND", "/dav/")


class TestMockedServer:
    async def test_reverse_proxy_prefix(self) -> None:
        # Published as /dav/, while the server names itself /remote/u/.
        adapter, _ = mocked(
            {
                ROOT: httpx.Response(
                    207, text=multistatus(("/remote/u/", True))
                ),
                ("PROPFIND", "/dav/sub"): httpx.Response(
                    207,
                    text=multistatus(
                        ("/remote/u/sub/", True),
                        ("/remote/u/sub/a%20b.txt", False),
                        ("/remote/u/sub/inner/", True),
                    ),
                ),
            }
        )

        entries = [entry async for entry in adapter.list("sub", deep=False)]

        assert [(e.path, e.is_file) for e in entries] == [
            ("sub/a b.txt", True),
            ("sub/inner", False),
        ]
        await adapter.aclose()

    async def test_root_without_href_uses_the_url(self) -> None:
        adapter, _ = mocked(
            {
                ROOT: httpx.Response(207, text=multistatus()),
                ("PROPFIND", "/dav/a.txt"): httpx.Response(
                    207, text=multistatus(("/dav/a.txt", False))
                ),
            }
        )

        assert (await adapter.stat("a.txt")).is_file
        await adapter.aclose()

    async def test_differently_spelled_href(self) -> None:
        adapter, _ = mocked(
            {
                ROOT: httpx.Response(207, text=multistatus(("/dav/", True))),
                ("PROPFIND", "/dav/a.txt"): httpx.Response(
                    207, text=multistatus(("/dav/A.TXT", False))
                ),
            }
        )

        assert (await adapter.stat("a.txt")).is_file
        await adapter.aclose()

    async def test_refused_mkcol(self) -> None:
        adapter, _ = mocked(
            {
                ROOT: httpx.Response(207, text=multistatus(("/dav/", True))),
                ("MKCOL", "/dav/new/"): httpx.Response(403),
            }
        )

        await adapter.create_directory("")
        with pytest.raises(WebdavError, match="MKCOL /new failed: 403"):
            await adapter.create_directory("new")
        await adapter.aclose()

    async def test_resources_vanishing_before_delete(self) -> None:
        adapter, seen = mocked(
            {
                ROOT: httpx.Response(207, text=multistatus(("/dav/", True))),
                ("PROPFIND", "/dav/a.txt"): httpx.Response(
                    207, text=multistatus(("/dav/a.txt", False))
                ),
                ("PROPFIND", "/dav/dir"): httpx.Response(
                    207, text=multistatus(("/dav/dir/", True))
                ),
            }
        )

        await adapter.delete_file("a.txt")
        await adapter.delete_directory("dir")

        assert ("DELETE", "/dav/a.txt") in seen
        assert ("DELETE", "/dav/dir/") in seen
        await adapter.aclose()

    async def test_replacing_a_file_in_a_folder(self) -> None:
        adapter, seen = mocked(
            {
                ROOT: httpx.Response(207, text=multistatus(("/dav/", True))),
                ("PROPFIND", "/dav/d/a.txt"): httpx.Response(
                    207, text=multistatus(("/dav/d/a.txt", False))
                ),
                ("PROPFIND", "/dav/d/b.txt"): httpx.Response(
                    207, text=multistatus(("/dav/d/b.txt", False))
                ),
                ("MOVE", "/dav/d/a.txt"): httpx.Response(412),
            }
        )

        with pytest.raises(WebdavError, match=r"MOVE /d/a\.txt failed: 412"):
            await adapter.move_file("d/a.txt", "d/b.txt")

        # Overwrite: F, then T over the file; no parent was created.
        assert seen.count(("MOVE", "/dav/d/a.txt")) == 2
        assert ("MKCOL", "/dav/d/") not in seen
        await adapter.aclose()

    async def test_temporary_file_that_keeps_coming_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("jcpy.storage.webdav.DISCARD_DELAY", 0)
        adapter, seen = mocked(
            {
                ROOT: httpx.Response(207, text=multistatus(("/dav/", True))),
                ("PROPFIND", "/dav/.tmp"): httpx.Response(
                    207, text=multistatus(("/dav/.tmp", False))
                ),
                ("DELETE", "/dav/.tmp"): httpx.Response(204),
            }
        )

        await adapter._discard(".tmp")

        assert seen.count(("DELETE", "/dav/.tmp")) == 3
        await adapter.aclose()

    async def test_anonymous_access(self) -> None:
        adapter = WebdavStorageAdapter(
            WebdavOptions.model_validate({"url": "https://h/dav/"})
        )

        client = adapter._http()

        assert client.auth is None
        assert "authorization" not in client.headers
        await adapter.aclose()


class TestParsing:
    def test_parse_multistatus(self) -> None:
        body = b"""<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response>
            <d:href>/dav/base/</d:href>
            <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
            </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
          </d:response>
          <d:response>
            <d:href>https://h/dav/base/a%20b.txt</d:href>
            <d:propstat><d:prop><d:resourcetype/>
              <d:getcontentlength>12</d:getcontentlength>
              <d:getlastmodified>Fri, 25 Sep 2026 12:00:00 GMT
              </d:getlastmodified>
            </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
            <d:propstat><d:prop><d:getetag/></d:prop>
            <d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>
          </d:response>
          <d:response>
            <d:href>/dav/base/sub</d:href>
            <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
              <d:getlastmodified>garbage</d:getlastmodified>
            </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
          </d:response>
          <d:response><d:href>/other/x</d:href></d:response>
        </d:multistatus>"""

        assert parse_multistatus(body, "/dav/base/") == [
            DavEntry("", is_directory=True),
            DavEntry("a b.txt", False, 12, 1790337600000.0),
            DavEntry("sub", is_directory=True),
        ]
