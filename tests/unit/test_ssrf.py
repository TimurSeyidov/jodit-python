"""SSRF guard for remote downloads."""

from io import BytesIO
from typing import TYPE_CHECKING

import httpx
import pytest

from jcpy.errors import HttpError
from jcpy.helpers.ssrf import (
    MAX_REDIRECTS,
    DownloadTooLargeError,
    check_url,
    download,
    download_to,
    is_private_address,
    resolve_host,
)
from jcpy.helpers.urls import parse_url

if TYPE_CHECKING:
    from collections.abc import Callable

PUBLIC_V4 = "93.184.216.34"
HOST_REFUSED = "Requests to this host are not allowed"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


def resolver(table: dict[str, list[str]]) -> Callable[..., object]:
    async def resolve(host: str, port: int) -> list[str]:
        if host not in table:
            msg = f"unknown host {host}"
            raise OSError(msg)
        return table[host]

    return resolve


@pytest.mark.parametrize(
    ("address", "private"),
    [
        ("8.8.8.8", False),
        (PUBLIC_V6, False),
        ("::ffff:8.8.8.8", False),
        ("127.0.0.1", True),
        ("10.1.2.3", True),
        ("100.64.0.1", True),
        ("169.254.169.254", True),
        ("172.16.0.1", True),
        ("192.0.0.9", True),
        ("192.168.1.1", True),
        ("198.18.0.1", True),
        ("224.0.0.1", True),
        ("240.0.0.1", True),
        ("0.0.0.0", True),  # noqa: S104 - an address under test
        ("::1", True),
        ("::", True),
        ("fc00::1", True),
        ("fe80::1%lo0", True),
        ("ff02::1", True),
        ("::ffff:127.0.0.1", True),
        ("::ffff:7f00:1", True),
        ("64:ff9b::a9fe:a9fe", True),
        ("2002:7f00:1::", True),
        ("2001:0:4136:e378:8000:63bf:80ff:fffe", True),
        ("not-an-ip", True),
    ],
)
def test_is_private_address(address: str, private: bool) -> None:
    assert is_private_address(address) is private


@pytest.mark.parametrize(
    ("url", "status", "message"),
    [
        ("not-a-valid-url", 400, "Invalid URL"),
        ("file:///etc/passwd", 400, "Only http and https URLs are allowed"),
        ("ftp://example.com/a", 400, "Only http and https URLs are allowed"),
        ("http://localhost/a", 403, "Requests to this host are not allowed"),
        (
            "http://api.localhost/a",
            403,
            "Requests to this host are not allowed",
        ),
        (
            "http://printer.local/a",
            403,
            "Requests to this host are not allowed",
        ),
        (
            "http://127.0.0.1/a",
            403,
            "Requests to private or local addresses are not allowed",
        ),
        (
            "http://[::1]:8080/a",
            403,
            "Requests to private or local addresses are not allowed",
        ),
        (
            "http://mixed.example/a",
            403,
            "Requests to private or local addresses are not allowed",
        ),
        ("http://nowhere.example/a", 400, "Could not resolve URL host"),
        ("http://empty.example/a", 400, "Could not resolve URL host"),
    ],
)
async def test_check_url_refusals(url: str, status: int, message: str) -> None:
    resolve = resolver(
        {"mixed.example": [PUBLIC_V4, "10.0.0.1"], "empty.example": []}
    )

    with pytest.raises(HttpError, match=message) as info:
        await check_url(url, resolve)  # type: ignore[arg-type]

    assert info.value.status_code == status


async def test_check_url_pins_the_address() -> None:
    resolve = resolver({"files.example": [PUBLIC_V4, "93.184.216.35"]})

    target = await check_url(
        "https://user:pw@files.example:8443/a.png?v=1",
        resolve,  # type: ignore[arg-type]
    )

    assert str(target.url) == f"https://user:pw@{PUBLIC_V4}:8443/a.png?v=1"
    assert target.host == "files.example:8443"
    assert target.server_name == "files.example"


async def test_check_url_ip_literals() -> None:
    v6 = await check_url(f"http://[{PUBLIC_V6}]/a")
    v4 = await check_url(f"http://{PUBLIC_V4}/a")

    assert v6.url.host == PUBLIC_V6
    assert v6.server_name is None
    assert v4.host == PUBLIC_V4


async def test_resolve_host_uses_system_resolver() -> None:
    assert "127.0.0.1" in await resolve_host("127.0.0.1", 80)


class Server:
    """Programmable responses keyed by host header and path."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, httpx.Response] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.headers['host']}{request.url.path}"
        return self.routes.get(key, httpx.Response(404))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


PUBLIC = resolver(
    {
        "cdn.example": [PUBLIC_V4],
        "other.example": ["8.8.4.4"],
        "internal.example": ["169.254.169.254"],
    }
)


async def fetch(
    server: Server, url: str, *, guard: bool = True, limit: int | None = None
) -> bytes:
    return await download(
        url,
        guard=guard,
        limit=limit,
        network_timeout=5,
        resolver=PUBLIC,  # type: ignore[arg-type]
        transport=server.transport(),
    )


async def test_download_connects_to_the_checked_address() -> None:
    server = Server()
    server.routes["cdn.example/a.png"] = httpx.Response(200, content=b"png")

    body = await fetch(server, "https://cdn.example/a.png")

    assert body == b"png"
    (request,) = server.requests
    assert request.url.host == PUBLIC_V4
    assert request.headers["host"] == "cdn.example"
    assert request.extensions["sni_hostname"] == "cdn.example"


async def test_every_redirect_hop_is_checked() -> None:
    server = Server()
    server.routes["cdn.example/start"] = httpx.Response(
        302, headers={"Location": "http://other.example/next"}
    )
    server.routes["other.example/next"] = httpx.Response(
        301, headers={"Location": "/final"}
    )
    server.routes["other.example/final"] = httpx.Response(200, content=b"ok")

    assert await fetch(server, "http://cdn.example/start") == b"ok"
    assert [str(r.url) for r in server.requests] == [
        f"http://{PUBLIC_V4}/start",
        "http://8.8.4.4/next",
        "http://8.8.4.4/final",
    ]


async def test_redirect_to_private_address_is_blocked() -> None:
    server = Server()
    server.routes["cdn.example/start"] = httpx.Response(
        302, headers={"Location": "http://internal.example/latest"}
    )

    with pytest.raises(HttpError, match="private or local") as info:
        await fetch(server, "http://cdn.example/start")

    assert info.value.status_code == 403
    assert len(server.requests) == 1


async def test_too_many_redirects() -> None:
    server = Server()
    server.routes["cdn.example/loop"] = httpx.Response(
        302, headers={"Location": "/loop"}
    )

    with pytest.raises(HttpError, match="Too many redirects"):
        await fetch(server, "http://cdn.example/loop")

    assert len(server.requests) == MAX_REDIRECTS + 1


async def test_redirect_without_location_is_a_response() -> None:
    server = Server()
    server.routes["cdn.example/a"] = httpx.Response(304)

    with pytest.raises(HttpError, match="File was not loaded: HTTP 304"):
        await fetch(server, "http://cdn.example/a")


async def test_unguarded_download_keeps_the_url() -> None:
    server = Server()
    server.routes["127.0.0.1/a"] = httpx.Response(200, content=b"x")

    assert await fetch(server, "http://127.0.0.1/a", guard=False) == b"x"
    assert "sni_hostname" not in server.requests[0].extensions


async def test_http_errors() -> None:
    with pytest.raises(HttpError, match="File was not loaded: HTTP 404"):
        await fetch(Server(), "http://cdn.example/missing")


async def test_network_errors() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        msg = "connection refused"
        raise httpx.ConnectError(msg, request=request)

    with pytest.raises(
        HttpError, match="File was not loaded: connection refused"
    ):
        await download(
            "http://cdn.example/a",
            guard=True,
            limit=None,
            network_timeout=5,
            resolver=PUBLIC,  # type: ignore[arg-type]
            transport=httpx.MockTransport(fail),
        )


async def test_size_limit_stops_the_download() -> None:
    server = Server()
    server.routes["cdn.example/big"] = httpx.Response(200, content=b"x" * 11)

    assert await fetch(server, "http://cdn.example/big", limit=11)
    with pytest.raises(DownloadTooLargeError):
        await fetch(server, "http://cdn.example/big", limit=10)


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("", False),
        ("nope", False),
        ("http://x", True),
        ("ftp://x/a", True),
        ("mailto:a@b", True),
        ("http://", False),
        ("http:x", True),
        ("https://ex ample.com", False),
        ("http://a_b.com/x", True),
        ("http://127.0.0.1:99999/", False),
        ("//x.com/a", False),
        ("http://x.com/a b", True),
        ("http://[::1/a", False),
        ("http://[::1]x/", False),
    ],
)
def test_url_validity_matches_zod(url: str, valid: bool) -> None:
    assert (parse_url(url) is not None) is valid


def test_parse_url_parts() -> None:
    parsed = parse_url("HTTPS://User@Example.COM:8443/a/../b?q#f")

    assert parsed is not None
    assert (parsed.scheme, parsed.hostname, parsed.port, parsed.pathname) == (
        "https",
        "example.com",
        8443,
        "/b",
    )


async def test_download_to_writes_the_body_into_a_file() -> None:
    server = Server()
    server.routes["cdn.example/big"] = httpx.Response(
        200, content=b"x" * 70_000
    )
    target = BytesIO()

    written = await download_to(
        "http://cdn.example/big",
        target,
        guard=True,
        limit=None,
        network_timeout=5,
        resolver=PUBLIC,  # type: ignore[arg-type]
        transport=server.transport(),
    )

    assert written == 70_000
    assert target.getvalue() == b"x" * 70_000


async def test_download_to_respects_the_limit() -> None:
    server = Server()
    server.routes["cdn.example/big"] = httpx.Response(200, content=b"x" * 100)

    with pytest.raises(DownloadTooLargeError):
        await download_to(
            "http://cdn.example/big",
            BytesIO(),
            guard=True,
            limit=10,
            network_timeout=5,
            resolver=PUBLIC,  # type: ignore[arg-type]
            transport=server.transport(),
        )
