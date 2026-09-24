"""Mapping public file URLs back to source files."""

import posixpath
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

from jcpy.helpers.urls import url_pathname

if TYPE_CHECKING:
    from jcpy.sources import Source


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
