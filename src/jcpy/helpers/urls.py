"""URL parsing with the acceptance rules of the WHATWG ``URL`` class."""

import re
from dataclasses import dataclass

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):(.*)$", re.DOTALL)
_SPECIAL_SCHEMES = frozenset({"http", "https", "ws", "wss", "ftp", "file"})
_TRIM = "".join(chr(code) for code in range(0x21))
_MAX_PORT = 65535
_FORBIDDEN_HOST = re.compile(r"[\x00-\x20#%/:<>?@\[\\\]^|\x7f]")
_DOT = frozenset({".", "%2e", "%2E"})
_DOUBLE_DOT = frozenset(
    {"..", ".%2e", ".%2E", "%2e.", "%2E.", "%2e%2e", "%2E%2E", "%2e%2E"}
    | {"%2E%2e"}
)


@dataclass(frozen=True, slots=True)
class ParsedUrl:
    """Parts of an absolute URL.

    Attributes:
        scheme: Lower-cased scheme without ``:``.
        hostname: Lower-cased host; IPv6 keeps its brackets; empty for
            URLs without authority.
        port: Explicit port, ``None`` when absent.
        pathname: Path with dot segments resolved, still
            percent-encoded.
    """

    scheme: str
    hostname: str
    port: int | None
    pathname: str


def _remove_dot_segments(path: str) -> str:
    segments = path.split("/")[1:]
    output: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment in _DOUBLE_DOT:
            if output:
                output.pop()
            if last:
                output.append("")
        elif segment in _DOT:
            if last:
                output.append("")
        else:
            output.append(segment)
    return "/" + "/".join(output)


def _split_host(authority: str) -> tuple[str, str] | None:
    """Split ``host[:port]``; ``None`` for a malformed IPv6 literal."""
    host = authority.rpartition("@")[2]
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return None
        rest = host[end + 1 :]
        if rest and not rest.startswith(":"):
            return None
        return host[: end + 1], rest[1:]
    if ":" in host:
        hostname, _, port = host.rpartition(":")
        return hostname, port
    return host, ""


def parse_url(url: str) -> ParsedUrl | None:
    """Parse an absolute URL, rejecting what ``new URL(url)`` rejects.

    A scheme is required; special schemes other than ``file`` need a
    host without forbidden characters and a valid port. Fragments and
    queries are dropped.

    Args:
        url: Absolute URL.

    Returns:
        URL parts, ``None`` for an invalid URL.
    """
    cleaned = url.strip(_TRIM).replace("\t", "").replace("\n", "")
    match = _SCHEME.match(cleaned)
    if match is None:
        return None
    scheme, rest = match.group(1).lower(), match.group(2)
    rest = re.split(r"[?#]", rest, maxsplit=1)[0]
    if scheme not in _SPECIAL_SCHEMES:
        return ParsedUrl(scheme, "", None, rest)
    rest = rest.replace("\\", "/")
    if scheme == "file":
        if not rest.startswith("//"):
            return ParsedUrl(
                scheme, "", None, _remove_dot_segments("/" + rest.lstrip("/"))
            )
        host, _, path = rest[2:].partition("/")
        return ParsedUrl(
            scheme, host.lower(), None, _remove_dot_segments("/" + path)
        )

    authority, _, path = rest.lstrip("/").partition("/")
    split = _split_host(authority)
    if split is None:
        return None
    hostname, port = split
    if port and (not port.isdigit() or int(port) > _MAX_PORT):
        return None
    if not hostname or (
        not hostname.startswith("[") and _FORBIDDEN_HOST.search(hostname)
    ):
        return None
    return ParsedUrl(
        scheme,
        hostname.lower(),
        int(port) if port else None,
        _remove_dot_segments("/" + path),
    )


def url_pathname(url: str) -> str | None:
    """Return the path of an absolute URL like ``new URL(url).pathname``.

    Args:
        url: Absolute URL.

    Returns:
        Percent-encoded path, ``None`` for an invalid URL.
    """
    parsed = parse_url(url)
    return None if parsed is None else parsed.pathname
