"""Downloads of user-supplied URLs without server-side request forgery.

Every hop (the URL and each redirect target) is checked: only
``http``/``https``, no local host names, and every address the host
resolves to must be public. The connection then goes to the checked
address itself, with the original ``Host`` header and TLS server name,
so a second DNS answer cannot redirect it (DNS rebinding).
"""

import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import anyio
import httpx

from jcpy.errors import HttpError
from jcpy.helpers.urls import parse_url

MAX_REDIRECTS = 5

type Resolver = Callable[[str, int], Awaitable[list[str]]]
"""Resolve a host name and port to IP addresses."""

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Blocked explicitly in case the stdlib considers any of their members
# global.
_BLOCKED_IPV4 = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_LOCAL_SUFFIXES = (".localhost", ".local")


@dataclass(frozen=True, slots=True)
class Target:
    """Checked destination of one request.

    Attributes:
        url: URL to request (host replaced by ``address`` when pinned).
        host: ``Host`` header value, ``None`` to keep the URL's.
        server_name: TLS server name, ``None`` for plain HTTP.
    """

    url: httpx.URL
    host: str | None = None
    server_name: str | None = None


async def resolve_host(host: str, port: int) -> list[str]:
    """Resolve a host name with the system resolver.

    Args:
        host: Host name.
        port: Port of the request.

    Returns:
        IP addresses in resolver order.

    Raises:
        OSError: The name cannot be resolved.
    """
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _embedded_ipv4(
    address: ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | None:
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    if address in _NAT64:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def is_private_address(address: str) -> bool:
    """Tell whether an address must not be contacted.

    Everything that is not globally routable is private: loopback,
    private and shared ranges, link-local (cloud metadata), multicast,
    reserved and documentation ranges. IPv6 forms embedding an IPv4
    address (mapped, 6to4, Teredo, NAT64) are judged by that address.

    Args:
        address: IPv4 or IPv6 address, optionally with a ``%zone``.

    Returns:
        ``True`` for private or invalid addresses.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            ip = embedded
    if isinstance(ip, ipaddress.IPv4Address) and any(
        ip in network for network in _BLOCKED_IPV4
    ):
        return True
    return ip.is_multicast or not ip.is_global


async def check_url(url: str, resolver: Resolver = resolve_host) -> Target:
    """Check one URL and pin it to a verified public address.

    Args:
        url: Absolute URL.
        resolver: Host name resolver.

    Returns:
        Request target connecting to the first verified address.

    Raises:
        HttpError: ``400 Invalid URL``, ``400 Only http and https URLs
            are allowed``, ``403`` for local host names or private
            addresses, ``400 Could not resolve URL host``.
    """
    parsed = parse_url(url)
    if parsed is None:
        raise HttpError.bad_request("Invalid URL")
    if parsed.scheme not in {"http", "https"}:
        raise HttpError.bad_request("Only http and https URLs are allowed")

    host = parsed.hostname.strip("[]")
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        raise HttpError.forbidden("Requests to this host are not allowed")

    request_url = httpx.URL(url)
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = await resolver(host, request_url.port or 0)
        except OSError:
            raise HttpError.bad_request("Could not resolve URL host") from None
    if not addresses:
        raise HttpError.bad_request("Could not resolve URL host")
    if any(is_private_address(address) for address in addresses):
        raise HttpError.forbidden(
            "Requests to private or local addresses are not allowed"
        )

    authority = request_url.netloc.decode("ascii").rpartition("@")[2]
    return Target(
        url=request_url.copy_with(host=addresses[0].split("%", 1)[0]),
        host=authority,
        server_name=host if parsed.scheme == "https" else None,
    )


class DownloadTooLargeError(HttpError):
    """The downloaded body exceeded the size limit."""

    def __init__(self) -> None:
        super().__init__(403, "File size exceeds the allowable")


@dataclass(frozen=True, slots=True)
class Fetched:
    """Downloaded resource.

    Attributes:
        url: Final URL after redirects.
        body: Response body.
        content_type: ``Content-Type`` header, when sent.
    """

    url: str
    body: bytes
    content_type: str | None


async def fetch(
    url: str,
    *,
    guard: bool,
    limit: int | None,
    network_timeout: float,
    resolver: Resolver = resolve_host,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Fetched:
    """Download a URL, re-checking every redirect hop.

    Args:
        url: URL to download.
        guard: Apply the SSRF checks (off only for trusted networks).
        limit: Abort once the body exceeds this many bytes.
        network_timeout: Network timeout in seconds.
        resolver: Host name resolver for the checks.
        transport: HTTP transport (for tests).

    Returns:
        Final URL, body and content type.

    Raises:
        HttpError: SSRF refusals (see ``check_url``), ``400 Too many
            redirects``, ``400 File was not loaded: HTTP <status>`` for
            unsuccessful responses, ``400 File was not loaded: <reason>``
            for network errors.
        DownloadTooLargeError: The body exceeds ``limit``.
    """
    current = url
    hops = 0
    async with httpx.AsyncClient(
        transport=transport,
        timeout=network_timeout,
        follow_redirects=False,
    ) as client:
        while True:
            target = (
                await check_url(current, resolver)
                if guard
                else Target(httpx.URL(current))
            )
            headers = {"Host": target.host} if target.host else {}
            extensions = (
                {"sni_hostname": target.server_name}
                if target.server_name
                else {}
            )
            try:
                async with client.stream(
                    "GET", target.url, headers=headers, extensions=extensions
                ) as response:
                    location = response.headers.get("location")
                    if 300 <= response.status_code < 400 and location:
                        if hops == MAX_REDIRECTS:
                            raise HttpError.bad_request("Too many redirects")
                        hops += 1
                        current = str(httpx.URL(current).join(location))
                        continue
                    if not response.is_success:
                        msg = (
                            f"File was not loaded: HTTP {response.status_code}"
                        )
                        raise HttpError.bad_request(msg)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if limit is not None and len(body) > limit:
                            raise DownloadTooLargeError
                    return Fetched(
                        current,
                        bytes(body),
                        response.headers.get("content-type"),
                    )
            except httpx.HTTPError as error:
                msg = f"File was not loaded: {error}"
                raise HttpError.bad_request(msg) from None


async def download(
    url: str,
    *,
    guard: bool,
    limit: int | None,
    network_timeout: float,
    resolver: Resolver = resolve_host,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Download a URL body; see ``fetch`` for the checks and errors.

    Args:
        url: URL to download.
        guard: Apply the SSRF checks (off only for trusted networks).
        limit: Abort once the body exceeds this many bytes.
        network_timeout: Network timeout in seconds.
        resolver: Host name resolver for the checks.
        transport: HTTP transport (for tests).

    Returns:
        Response body.

    Raises:
        HttpError: See ``fetch``.
        DownloadTooLargeError: The body exceeds ``limit``.
    """
    fetched = await fetch(
        url,
        guard=guard,
        limit=limit,
        network_timeout=network_timeout,
        resolver=resolver,
        transport=transport,
    )
    return fetched.body
