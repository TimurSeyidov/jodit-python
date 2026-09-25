"""Storage adapter for WebDAV servers (Apache, nginx, Nextcloud...)."""

import contextlib
import uuid
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit

import anyio
import httpx
from anyio import CancelScope, to_thread

from jcpy.storage.base import CHUNK_SIZE, FileWasNotFoundError, StatEntry

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator
    from typing import BinaryIO

    from jcpy.config.models import WebdavOptions

DAV = "{DAV:}"
DISCARD_ATTEMPTS = 3
"""Removals of a temporary file tried after a failed upload."""
DISCARD_DELAY = 0.1
"""Seconds between those removals."""
PROPFIND_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:"><d:prop>'
    b"<d:resourcetype/><d:getcontentlength/><d:getlastmodified/>"
    b"</d:prop></d:propfind>"
)


class WebdavError(OSError):
    """A WebDAV request failed.

    The message names the storage path, not the server URL.

    Args:
        method: HTTP method.
        path: Storage path.
        response: Server answer.
    """

    def __init__(
        self, method: str, path: str, response: httpx.Response
    ) -> None:
        super().__init__(
            f"{method} /{path} failed: {response.status_code} "
            f"{response.reason_phrase}".rstrip()
        )
        self.status_code = response.status_code


@dataclass(frozen=True, slots=True)
class DavEntry:
    """Resource described by a ``PROPFIND`` answer.

    Attributes:
        path: Path relative to the base URL, without slashes around.
        is_directory: Whether it is a collection.
        size: Size in bytes of a file.
        last_modified_ms: Modification time in epoch milliseconds.
    """

    path: str
    is_directory: bool
    size: int | None = None
    last_modified_ms: float | None = None


def _milliseconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).timestamp() * 1000
    except TypeError, ValueError:
        return None


def parse_multistatus(body: bytes, base_path: str) -> list[DavEntry]:
    """Parse a ``PROPFIND`` multistatus answer.

    Args:
        body: XML answer.
        base_path: Decoded path of the base URL, ending with ``/``.

    Returns:
        Resources under ``base_path`` (the base itself as ``""``);
        others are left out.
    """
    entries: list[DavEntry] = []
    # The server is the operator's own; expat (2.4+) caps entity
    # expansion and ElementTree never loads external entities.
    root = ElementTree.fromstring(body)  # noqa: S314
    for response in root.iter(f"{DAV}response"):
        href = response.findtext(f"{DAV}href", "").strip()
        path = unquote(urlsplit(href).path)
        if not (path + "/").startswith(base_path):
            continue
        relative = path[len(base_path) :].strip("/")
        props = [
            propstat.find(f"{DAV}prop")
            for propstat in response.iter(f"{DAV}propstat")
            if " 200 " in f"{propstat.findtext(f'{DAV}status', '')} "
        ]
        found = [prop for prop in props if prop is not None]
        is_directory = any(
            prop.find(f"{DAV}resourcetype/{DAV}collection") is not None
            for prop in found
        )
        length = next(
            (
                text
                for prop in found
                if (text := prop.findtext(f"{DAV}getcontentlength"))
            ),
            None,
        )
        modified = next(
            (
                text
                for prop in found
                if (text := prop.findtext(f"{DAV}getlastmodified"))
            ),
            None,
        )
        entries.append(
            DavEntry(
                path=relative,
                is_directory=is_directory,
                size=(
                    int(length)
                    if not is_directory and length and length.isdigit()
                    else None
                ),
                last_modified_ms=_milliseconds(modified),
            )
        )
    return entries


def first_href(body: bytes) -> str | None:
    """Decoded path of the first resource of a multistatus answer.

    Args:
        body: XML answer.

    Returns:
        The path, or ``None`` when the answer names no resource.
    """
    root = ElementTree.fromstring(body)  # noqa: S314 - see parse_multistatus
    href = root.findtext(f"{DAV}response/{DAV}href")
    return unquote(urlsplit(href.strip()).path) if href else None


def _parent(path: str) -> str:
    return path.rpartition("/")[0]


class WebdavStorageAdapter:
    """Storage adapter for a collection on a WebDAV server.

    Uploads go to a temporary file that is then moved over the target;
    copies and moves run on the server. A file never replaces a
    collection: ``Overwrite`` is only allowed over files.

    Args:
        options: WebDAV settings.
    """

    def __init__(self, options: WebdavOptions) -> None:
        self.options = options
        self.base_url = options.url.rstrip("/") + "/"
        self._href_base: str | None = None
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            options = self.options
            auth: httpx.Auth | None = None
            headers: dict[str, str] = {}
            if options.token is not None:
                headers["Authorization"] = f"Bearer {options.token}"
            elif options.username is not None:
                credentials = (options.username, options.password or "")
                auth = (
                    httpx.DigestAuth(*credentials)
                    if options.auth == "digest"
                    else httpx.BasicAuth(*credentials)
                )
            self._client = httpx.AsyncClient(
                auth=auth,
                headers=headers,
                timeout=options.timeout,
                follow_redirects=True,
                transport=httpx.AsyncHTTPTransport(
                    verify=options.verify_certificate,
                    retries=1,
                    limits=httpx.Limits(
                        max_connections=options.connections,
                        max_keepalive_connections=options.connections,
                    ),
                ),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _url(self, path: str, *, directory: bool = False) -> str:
        if not path:
            return self.base_url
        quoted = "/".join(quote(part, safe="") for part in path.split("/"))
        return self.base_url + quoted + ("/" if directory else "")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        directory: bool = False,
        headers: dict[str, str] | None = None,
        content: bytes | AsyncIterator[bytes] | None = None,
    ) -> httpx.Response:
        return await self._http().request(
            method,
            self._url(path, directory=directory),
            headers=headers,
            content=content,
        )

    @staticmethod
    def _check(method: str, path: str, response: httpx.Response) -> None:
        if response.status_code == httpx.codes.NOT_FOUND:
            raise FileNotFoundError(path)
        if response.is_error:
            raise WebdavError(method, path, response)

    async def _hrefs_base(self) -> str:
        """Path the server's ``href`` values start with for the root.

        Taken from the server's answer rather than the configured URL:
        a reverse proxy may serve the share under another path.
        """
        if self._href_base is None:
            body = await self._propfind_body("", "0")
            path = first_href(body) or unquote(urlsplit(self.base_url).path)
            self._href_base = path.rstrip("/") + "/"
        return self._href_base

    async def _propfind(
        self, path: str, depth: str
    ) -> builtins.list[DavEntry]:
        body = await self._propfind_body(path, depth)
        return parse_multistatus(body, await self._hrefs_base())

    async def _propfind_body(self, path: str, depth: str) -> bytes:
        response = await self._request(
            "PROPFIND",
            path,
            headers={"Depth": depth, "Content-Type": "application/xml"},
            content=PROPFIND_BODY,
        )
        self._check("PROPFIND", path, response)
        if response.status_code != httpx.codes.MULTI_STATUS:
            raise WebdavError("PROPFIND", path, response)
        return response.content

    async def _find(self, path: str) -> DavEntry | None:
        try:
            entries = await self._propfind(path, "0")
        except FileNotFoundError:
            return None
        for entry in entries:
            if entry.path == path:
                return entry
        return entries[0] if entries else None

    @staticmethod
    def _stat_entry(path: str, entry: DavEntry) -> StatEntry:
        if entry.is_directory:
            return StatEntry(
                path,
                is_file=False,
                last_modified_ms=entry.last_modified_ms or 0,
            )
        return StatEntry(
            path,
            is_file=True,
            size=entry.size or 0,
            last_modified_ms=entry.last_modified_ms or 0,
        )

    async def _make_directories(self, path: str) -> None:
        if not path:
            return
        response = await self._request("MKCOL", path, directory=True)
        if response.status_code == httpx.codes.CONFLICT:
            await self._make_directories(_parent(path))
            response = await self._request("MKCOL", path, directory=True)
        if response.is_success:
            return
        # 405: something exists there already.
        entry = await self._find(path)
        if entry is not None and entry.is_directory:
            return
        if entry is not None:
            raise FileExistsError(path)
        self._check("MKCOL", path, response)

    async def _created_parent(
        self, response: httpx.Response, path: str
    ) -> bool:
        """Make sure the parent folder a failed request needed exists.

        RFC 4918 answers ``409`` for a missing parent, but servers also
        use ``403``, ``404`` or ``500``, and a concurrent request may have
        created the folder meanwhile: any failure gets one more try.

        Returns:
            Whether the request is worth repeating.
        """
        parent = _parent(path)
        if not response.is_error or not parent:
            return False
        if response.status_code == httpx.codes.PRECONDITION_FAILED:
            return False
        if not await self.directory_exists(parent):
            await self._make_directories(parent)
        return True

    async def _discard(self, path: str) -> None:
        """Best-effort removal of a temporary file after a failure.

        A server may still be finishing an aborted upload and write the
        file after it was deleted: it is checked again a few times.
        """
        with contextlib.suppress(Exception):
            for _ in range(DISCARD_ATTEMPTS):
                await self._request("DELETE", path)
                await anyio.sleep(DISCARD_DELAY)
                if await self._find(path) is None:
                    return

    async def _relocate(
        self, method: str, source: str, destination: str, *, is_file: bool
    ) -> None:
        """``COPY``/``MOVE`` a resource, replacing only a file."""

        async def send(overwrite: str) -> httpx.Response:
            return await self._request(
                method,
                source,
                directory=not is_file,
                headers={
                    "Destination": self._url(
                        destination, directory=not is_file
                    ),
                    "Overwrite": overwrite,
                },
            )

        response = await send("F")
        if await self._created_parent(response, destination):
            response = await send("F")
        if response.status_code == httpx.codes.PRECONDITION_FAILED:
            target = await self._find(destination)
            if is_file and target is not None and not target.is_directory:
                response = await send("T")
            else:
                raise FileExistsError(destination)
        self._check(method, source, response)

    # --- StorageAdapter ---------------------------------------------------

    async def write(self, path: str, contents: bytes) -> None:
        """Create or replace a file, creating parent directories.

        Args:
            path: File path.
            contents: File contents.
        """
        await self.write_file(path, BytesIO(contents))

    async def write_file(self, path: str, file: BinaryIO) -> None:
        """Upload a file from a readable binary file.

        The contents go to a temporary file in the target folder that is
        then moved over the target (never over a folder).

        Args:
            path: File path.
            file: Source positioned at the start of the contents.

        Raises:
            FileExistsError: A folder is at ``path``.
        """
        start = file.tell()
        size = await to_thread.run_sync(file.seek, 0, 2) - start
        parent = _parent(path)
        name = f".{uuid.uuid4().hex}.tmp"
        temporary = f"{parent}/{name}" if parent else name

        async def body() -> AsyncIterator[bytes]:
            await to_thread.run_sync(file.seek, start)
            while chunk := await to_thread.run_sync(file.read, CHUNK_SIZE):
                yield chunk

        async def upload() -> httpx.Response:
            try:
                return await self._request(
                    "PUT",
                    temporary,
                    headers={"Content-Length": str(size)},
                    content=body(),
                )
            except httpx.StreamConsumed:
                # Digest asked for a new challenge after the body was
                # sent; it is cached now, so the retry is signed upfront.
                return await self._request(
                    "PUT",
                    temporary,
                    headers={"Content-Length": str(size)},
                    content=body(),
                )

        try:
            response = await upload()
            if await self._created_parent(response, temporary):
                response = await upload()
            self._check("PUT", path, response)
            await self._relocate("MOVE", temporary, path, is_file=True)
        except BaseException:
            with CancelScope(shield=True):
                await self._discard(temporary)
            raise

    async def iter_file(self, path: str) -> AsyncIterator[bytes]:
        """Download a file in chunks.

        Args:
            path: File path.

        Yields:
            Chunks of at most ``CHUNK_SIZE`` bytes.

        Raises:
            FileWasNotFoundError: The file does not exist.
        """
        async with self._http().stream("GET", self._url(path)) as response:
            if response.status_code == httpx.codes.NOT_FOUND:
                raise FileWasNotFoundError(path)
            self._check("GET", path, response)
            async for chunk in response.aiter_bytes(CHUNK_SIZE):
                yield chunk

    async def read(self, path: str) -> bytes:
        """Download a whole file.

        Args:
            path: File path.

        Returns:
            File contents.

        Raises:
            FileWasNotFoundError: The file does not exist.
        """
        response = await self._request("GET", path)
        if response.status_code == httpx.codes.NOT_FOUND:
            raise FileWasNotFoundError(path)
        self._check("GET", path, response)
        return response.content

    async def delete_file(self, path: str) -> None:
        """Delete a file; a missing file is not an error.

        Args:
            path: File path.

        Raises:
            IsADirectoryError: ``path`` is a folder.
        """
        entry = await self._find(path)
        if entry is None:
            return
        if entry.is_directory:
            raise IsADirectoryError(path)
        response = await self._request("DELETE", path)
        if response.status_code != httpx.codes.NOT_FOUND:
            self._check("DELETE", path, response)

    async def create_directory(self, path: str) -> None:
        """Create a directory with its missing parents.

        Args:
            path: Directory path.
        """
        await self._make_directories(path)

    async def delete_directory(self, path: str) -> None:
        """Delete a directory recursively; missing is not an error.

        The root itself is kept: only its contents are deleted.

        Args:
            path: Directory path.
        """
        entry = await self._find(path)
        if entry is None:
            return
        targets = (
            [
                (item.path, item.is_directory)
                async for item in self._children("")
            ]
            if not path
            else [(path, entry.is_directory)]
        )
        for target, is_directory in targets:
            response = await self._request(
                "DELETE", target, directory=is_directory
            )
            if response.status_code != httpx.codes.NOT_FOUND:
                self._check("DELETE", target, response)

    async def stat(self, path: str) -> StatEntry:
        """Read metadata of a file or directory.

        Args:
            path: Entry path.

        Returns:
            Metadata with size and modification time.

        Raises:
            FileNotFoundError: The entry does not exist.
        """
        entry = await self._find(path)
        if entry is None:
            raise FileNotFoundError(path)
        return self._stat_entry(path, entry)

    async def _children(self, path: str) -> AsyncIterator[DavEntry]:
        for entry in await self._propfind(path, "1"):
            if entry.path != path:
                yield entry

    async def list(self, path: str, *, deep: bool) -> AsyncIterator[StatEntry]:
        """List a directory, one ``PROPFIND`` per folder.

        Args:
            path: Directory path.
            deep: Include nested entries.

        Yields:
            Entries in server order, with size and time.
        """
        pending = [path]
        while pending:
            current = pending.pop(0)
            async for entry in self._children(current):
                yield self._stat_entry(entry.path, entry)
                if deep and entry.is_directory:
                    pending.append(entry.path)

    async def file_exists(self, path: str) -> bool:
        """Tell whether a file exists.

        Args:
            path: File path.

        Returns:
            ``True`` for an existing file (not a directory).
        """
        entry = await self._find(path) if path else None
        return entry is not None and not entry.is_directory

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a directory exists.

        Args:
            path: Directory path.

        Returns:
            ``True`` for an existing directory (the root included).
        """
        entry = await self._find(path)
        return entry is not None and entry.is_directory

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy a file on the server (``COPY``).

        Args:
            source: Existing file path.
            destination: New file path.
        """
        await self._relocate("COPY", source, destination, is_file=True)

    async def move_file(self, source: str, destination: str) -> None:
        """Move a file or directory on the server (``MOVE``).

        Args:
            source: Existing path.
            destination: New path.

        Raises:
            FileNotFoundError: Nothing exists at ``source``.
        """
        entry = await self._find(source)
        if entry is None:
            raise FileNotFoundError(source)
        await self._relocate(
            "MOVE", source, destination, is_file=not entry.is_directory
        )
