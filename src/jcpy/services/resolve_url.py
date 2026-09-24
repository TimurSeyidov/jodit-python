"""Mapping public file URLs back to source files."""

import posixpath
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from jcpy.sources import Source

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):(.*)$", re.DOTALL)
_SPECIAL_SCHEMES = frozenset({"http", "https", "ws", "wss", "ftp", "file"})
_TRIM = "".join(chr(code) for code in range(0x21))
_MAX_PORT = 65535
_DOT = frozenset({".", "%2e", "%2E"})
_DOUBLE_DOT = frozenset(
    {"..", ".%2e", ".%2E", "%2e.", "%2E.", "%2e%2e", "%2E%2E", "%2e%2E"}
    | {"%2E%2e"}
)


@dataclass(frozen=True, slots=True)
class ResolvedFile:
    """Location of a file found by its URL.

    Attributes:
        path: Directory relative to the source root, starting with
            ``/``.
        name: File name.
        source: ``name`` setting of the source.
    """

    path: str
    name: str
    source: str


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


def url_pathname(url: str) -> str | None:
    """Parse a URL like the WHATWG ``URL`` constructor, keep its path.

    Only the checks needed to reject what ``new URL(url)`` rejects are
    implemented: a scheme is required, special schemes other than
    ``file`` need a host and a valid port.

    Args:
        url: Absolute URL.

    Returns:
        Path with dot segments resolved, still percent-encoded;
        ``None`` for an invalid URL.
    """
    match = _SCHEME.match(url.strip(_TRIM).replace("\t", "").replace("\n", ""))
    if match is None:
        return None
    scheme, rest = match.group(1).lower(), match.group(2)
    rest = re.split(r"[?#]", rest, maxsplit=1)[0]
    if scheme not in _SPECIAL_SCHEMES:
        return rest
    rest = rest.replace("\\", "/")
    if scheme == "file":
        if not rest.startswith("//"):
            return _remove_dot_segments("/" + rest.lstrip("/"))
        return _remove_dot_segments("/" + rest[2:].partition("/")[2])
    authority, _, path = rest.lstrip("/").partition("/")
    hostname = authority.rpartition("@")[2]
    port = ""
    if hostname.startswith("["):
        end = hostname.find("]")
        if end == -1:
            return None
        hostname, port = hostname[: end + 1], hostname[end + 1 :]
        if port and not port.startswith(":"):
            return None
        port = port[1:]
    elif ":" in hostname:
        hostname, _, port = hostname.rpartition(":")
    if port and (not port.isdigit() or int(port) > _MAX_PORT):
        return None
    if not hostname:
        return None
    return _remove_dot_segments("/" + path)


async def resolve_file_by_url(source: Source, url: str) -> ResolvedFile | None:
    """Find the file of a source that a public URL points to.

    The source ``baseurl`` path is stripped from the URL path; the rest
    (decoded) must be an existing file with a served extension. The
    host is not compared.

    Args:
        source: Source to search.
        url: Public URL of the file.

    Returns:
        File location, ``None`` when the source has no such file.
    """
    base = url_pathname(source.settings.baseurl) or "/"
    pathname = url_pathname(url)
    if pathname is None:
        return None
    prefix = re.compile("^(/)?" + re.escape(unquote(base)))
    pathname = prefix.sub("", unquote(pathname), count=1)
    root = await source.get_path()
    relative = pathname.removeprefix("/")
    try:
        stat = await source.storage.stat(relative)
    except Exception:
        return None
    if not stat.is_file or not source.is_safe_file(relative):
        return None

    directory = posixpath.dirname(
        posixpath.normpath(f"{root}/{pathname}")
    ).replace(root, "", 1)
    if not directory.startswith("/"):
        directory = "/" + directory
    return ResolvedFile(
        directory, posixpath.basename(pathname), source.settings.name
    )
