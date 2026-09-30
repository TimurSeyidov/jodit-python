"""Storage adapter for Google Cloud Storage.

Folders are emulated as in the ``s3`` adapter: a zero-byte object whose
name ends with ``/`` marks an explicitly created folder, and any name
with a ``/`` implies its parent folders.
"""

import contextlib
import mimetypes
from functools import partial
from io import BytesIO
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from google.oauth2 import service_account

from jcpy.helpers.concurrency import gather_limited
from jcpy.storage.base import CHUNK_SIZE, FileWasNotFoundError, StatEntry
from jcpy.storage.keys import build_key, normalize_key, strip_key_prefix
from jcpy.storage.streams import FullReader
from jcpy.storage.threads import TransferThreads

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator, Callable
    from datetime import datetime
    from typing import BinaryIO

    from jcpy.config.models import GcsOptions

PART_SIZE = 8 * 1024 * 1024
"""Bytes per request of large uploads and downloads (256 KiB multiple)."""

SCOPES = ["https://www.googleapis.com/auth/devstorage.read_write"]
"""OAuth scope the adapter needs."""

PUBLIC_ENDPOINT = "https://storage.googleapis.com"
"""Where public objects are served from."""


class _MissingObjectError(Exception):
    """An object expected by the caller is not there."""


class GcsStorageError(OSError):
    """A Cloud Storage request failed.

    The message holds the HTTP status, the service reason and the storage
    path, never the request URL.

    Args:
        operation: What was attempted.
        path: Storage path.
        error: SDK error.
    """

    def __init__(
        self, operation: str, path: str, error: GoogleAPICallError
    ) -> None:
        reasons = [
            str(item.get("reason"))
            for item in (error.errors or [])
            if isinstance(item, dict) and item.get("reason")
        ]
        detail = " ".join(
            str(part) for part in (error.code, *reasons[:1]) if part
        )
        super().__init__(
            f"{operation} /{path} failed: {detail or type(error).__name__}"
        )
        self.code = error.code


def _milliseconds(moment: datetime | None) -> float:
    return moment.timestamp() * 1000 if moment is not None else 0


def _content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def create_client(options: GcsOptions) -> storage.Client:
    """Create a Cloud Storage client for the settings.

    Args:
        options: GCS settings; ``credentialsFile`` is a service account
            key; without it and ``anonymous`` the Application Default
            Credentials are used
            (``GOOGLE_APPLICATION_CREDENTIALS``, workload identity, the
            metadata server, ``gcloud auth application-default login``).

    Returns:
        Client.
    """
    kwargs: dict[str, Any] = {}
    if options.endpoint is not None:
        kwargs["client_options"] = {"api_endpoint": options.endpoint}
    if options.anonymous:
        return storage.Client(
            project=options.project or "<none>",
            credentials=AnonymousCredentials(),
            **kwargs,
        )
    if options.credentials_file is not None:
        # Service account keys only: other credential configurations
        # (external accounts) can make requests to URLs they name.
        credentials = service_account.Credentials.from_service_account_file(
            options.credentials_file, scopes=SCOPES
        )
        return storage.Client(
            project=options.project or credentials.project_id,
            credentials=credentials,
            **kwargs,
        )
    return storage.Client(project=options.project, **kwargs)


class GcsStorageAdapter:
    """Storage adapter for one bucket (and optional name prefix).

    Uploads are atomic (an object appears when it is finalized); copies
    are server-side rewrites, whatever the object size.

    Args:
        options: GCS settings.
        client: Pre-configured client (tests, shared clients).
    """

    def __init__(
        self, options: GcsOptions, client: storage.Client | None = None
    ) -> None:
        self.options = options
        self.prefix = normalize_key(options.prefix or "")
        self.client = client or create_client(options)
        self.bucket = self.client.bucket(options.bucket)
        self._transfers = TransferThreads()
        base = options.public_base_url or (
            f"{PUBLIC_ENDPOINT}/{options.bucket}"
            + (f"/{self.prefix}" if self.prefix else "")
        )
        self.public_base_url = base.rstrip("/")

    def _name(self, path: str) -> str:
        return build_key(self.prefix, path)

    def _dir_name(self, path: str) -> str:
        name = self._name(path)
        if name:
            return f"{name}/"
        return f"{self.prefix}/" if self.prefix else ""

    def _path(self, name: str) -> str:
        return strip_key_prefix(self.prefix, name)

    def public_url(self, path: str) -> str:
        """Public URL of a stored file.

        Args:
            path: Storage path.

        Returns:
            ``publicBaseUrl`` (or the bucket URL) joined with the path.
        """
        normalized = normalize_key(path)
        if not normalized:
            return self.public_base_url
        return f"{self.public_base_url}/{normalized}"

    async def _call[T](
        self,
        operation: str,
        path: str,
        func: Callable[[], T],
        *,
        transfer: bool = False,
        missing: Callable[[str], Exception] | None = None,
    ) -> T:
        """Run a blocking SDK call, hiding request URLs from its errors.

        A ``404`` becomes ``missing(path)`` where the caller expects a
        missing object; elsewhere (a missing bucket) it is an error too.
        """
        try:
            if transfer:
                return await self._transfers.run(func)
            return await to_thread.run_sync(func)
        except NotFound as error:
            if missing is None:
                raise GcsStorageError(operation, path, error) from None
            raise missing(path) from None
        except GoogleAPICallError as error:
            raise GcsStorageError(operation, path, error) from None

    async def _refuse_directory(self, path: str) -> None:
        """Keep an object from shadowing a folder of the same name."""
        if normalize_key(path) and await self.directory_exists(path):
            raise IsADirectoryError(path)

    def _upload(self, path: str, file: BinaryIO, size: int) -> None:
        name = self._name(path)
        blob = self.bucket.blob(name, chunk_size=PART_SIZE)
        blob.cache_control = self.options.cache_control
        blob.storage_class = self.options.storage_class
        blob.upload_from_file(
            FullReader(file),
            size=size,
            content_type=_content_type(name),
            timeout=self.options.timeout,
        )

    async def write(self, path: str, contents: bytes) -> None:
        """Upload an object.

        Args:
            path: File path.
            contents: File contents.

        Raises:
            IsADirectoryError: A folder is at ``path``.
        """
        await self.write_file(path, BytesIO(contents))

    async def write_file(self, path: str, file: BinaryIO) -> None:
        """Upload an object from a readable binary file, in parts.

        Args:
            path: File path.
            file: Source positioned at the start of the contents.

        Raises:
            IsADirectoryError: A folder is at ``path``.
        """
        await self._refuse_directory(path)
        start = file.tell()
        size = await to_thread.run_sync(file.seek, 0, 2) - start
        await to_thread.run_sync(file.seek, start)
        await self._call(
            "write",
            path,
            partial(self._upload, path, file, size),
            transfer=True,
        )

    def _open(self, path: str) -> tuple[Any, bytes]:
        reader = self.bucket.blob(self._name(path)).open(
            "rb", chunk_size=PART_SIZE, timeout=self.options.timeout
        )
        try:
            first = reader.read(CHUNK_SIZE)
        except BaseException:
            reader.close()
            raise
        return reader, first

    async def iter_file(self, path: str) -> AsyncIterator[bytes]:
        """Download an object in chunks (at most 8 MB held at once).

        Args:
            path: File path.

        Yields:
            Chunks of at most ``CHUNK_SIZE`` bytes.

        Raises:
            FileWasNotFoundError: The object does not exist.
        """
        reader, chunk = await self._call(
            "read",
            path,
            partial(self._open, path),
            transfer=True,
            missing=FileWasNotFoundError,
        )
        try:
            while chunk:
                yield chunk
                chunk = await self._call(
                    "read",
                    path,
                    partial(reader.read, CHUNK_SIZE),
                    transfer=True,
                )
        finally:
            await to_thread.run_sync(reader.close)

    async def read(self, path: str) -> bytes:
        """Download a whole object.

        Args:
            path: File path.

        Returns:
            File contents.

        Raises:
            FileWasNotFoundError: The object does not exist.
        """
        blob = self.bucket.blob(self._name(path))
        return await self._call(
            "read",
            path,
            partial(blob.download_as_bytes, timeout=self.options.timeout),
            transfer=True,
            missing=FileWasNotFoundError,
        )

    async def delete_file(self, path: str) -> None:
        """Delete an object; a missing object is not an error.

        Args:
            path: File path.

        Raises:
            IsADirectoryError: ``path`` is a folder.
        """
        blob = self.bucket.blob(self._name(path))
        try:
            await self._call(
                "delete",
                path,
                partial(blob.delete, timeout=self.options.timeout),
                missing=_MissingObjectError,
            )
        except _MissingObjectError:
            if normalize_key(path) and await self.directory_exists(path):
                raise IsADirectoryError(path) from None

    async def create_directory(self, path: str) -> None:
        """Create a folder marker object.

        Args:
            path: Directory path; the root needs no marker.

        Raises:
            NotADirectoryError: A file is where a parent folder should be.
        """
        normalized = normalize_key(path)
        if not normalized:
            return
        parts = normalized.split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            if await self.file_exists(ancestor):
                raise NotADirectoryError(ancestor)
        marker = self.bucket.blob(self._dir_name(path))
        await self._call(
            "create folder",
            path,
            partial(
                marker.upload_from_string, b"", timeout=self.options.timeout
            ),
        )

    def _names(self, prefix: str) -> builtins.list[str]:
        return [
            blob.name
            for blob in self.client.list_blobs(
                self.bucket, prefix=prefix, timeout=self.options.timeout
            )
        ]

    async def _delete_all(self, path: str, names: builtins.list[str]) -> None:
        def delete(name: str) -> None:
            with contextlib.suppress(NotFound):
                self.bucket.blob(name).delete(timeout=self.options.timeout)

        await gather_limited(
            [
                partial(self._call, "delete", path, partial(delete, name))
                for name in names
            ]
        )

    async def delete_directory(self, path: str) -> None:
        """Delete every object below a folder, 16 requests at a time.

        A file at ``path`` is deleted too; the root itself stays.

        Args:
            path: Directory path.
        """
        if normalize_key(path) and await self.file_exists(path):
            await self.delete_file(path)
            return
        prefix = self._dir_name(path)
        names = await self._call(
            "delete folder", path, partial(self._names, prefix)
        )
        await self._delete_all(path, names)

    async def stat(self, path: str) -> StatEntry:
        """Describe an object, or a folder (explicit or implied).

        Args:
            path: Entry path.

        Returns:
            File metadata or a directory entry.

        Raises:
            FileNotFoundError: Neither an object nor a folder exists.
        """
        normalized = normalize_key(path)
        if not normalized:
            return StatEntry("", is_file=False, last_modified_ms=0)
        blob = await self._call(
            "stat",
            path,
            partial(
                self.bucket.get_blob,
                self._name(path),
                timeout=self.options.timeout,
            ),
        )
        if blob is not None:
            return StatEntry(
                normalized,
                is_file=True,
                size=blob.size or 0,
                last_modified_ms=_milliseconds(blob.updated),
            )
        if await self.directory_exists(path):
            return StatEntry(normalized, is_file=False, last_modified_ms=0)
        msg = f"Path not found: {path}"
        raise FileNotFoundError(msg)

    def _scan(self, path: str, deep: bool) -> builtins.list[StatEntry]:
        dir_name = self._dir_name(path)
        base = self._path(dir_name)
        seen: set[str] = set()
        entries: builtins.list[StatEntry] = []

        def add_directory(directory: str) -> None:
            if directory and directory not in seen:
                seen.add(directory)
                entries.append(
                    StatEntry(directory, is_file=False, last_modified_ms=0)
                )

        blobs = self.client.list_blobs(
            self.bucket,
            prefix=dir_name,
            delimiter=None if deep else "/",
            timeout=self.options.timeout,
        )
        for blob in blobs:
            name = blob.name
            if name == dir_name:
                continue
            if name.endswith("/"):
                add_directory(self._path(name))
                continue
            file_path = self._path(name)
            if deep:
                parent = base
                relative = file_path[len(base) :]
                for segment in [s for s in relative.split("/") if s][:-1]:
                    parent = f"{parent}/{segment}" if parent else segment
                    add_directory(parent)
            entries.append(
                StatEntry(
                    file_path,
                    is_file=True,
                    size=blob.size,
                    last_modified_ms=_milliseconds(blob.updated),
                )
            )
        # Folders below a shallow listing come as prefixes, after the pages.
        for prefix in sorted(blobs.prefixes):
            add_directory(self._path(prefix))
        return entries

    async def list(self, path: str, *, deep: bool) -> AsyncIterator[StatEntry]:
        """List a folder.

        Args:
            path: Directory path.
            deep: Include nested entries (implied folders included).

        Yields:
            Folders and files below the path.
        """
        for entry in await self._call(
            "list", path, partial(self._scan, path, deep)
        ):
            yield entry

    async def file_exists(self, path: str) -> bool:
        """Tell whether an object exists.

        Args:
            path: File path.

        Returns:
            ``True`` when the object exists; always ``False`` for the root.
        """
        if not normalize_key(path):
            return False
        blob = self.bucket.blob(self._name(path))
        return await self._call(
            "stat",
            path,
            partial(blob.exists, timeout=self.options.timeout),
        )

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a folder exists (marker or any object below it).

        Args:
            path: Directory path.

        Returns:
            ``True`` for the root and non-empty prefixes.
        """
        if not normalize_key(path):
            return True

        def any_object() -> bool:
            blobs = self.client.list_blobs(
                self.bucket,
                prefix=self._dir_name(path),
                max_results=1,
                timeout=self.options.timeout,
            )
            return any(True for _ in blobs)

        return await self._call("stat", path, any_object)

    def _copy_object(self, source_name: str, target_name: str) -> None:
        source = self.bucket.get_blob(
            source_name, timeout=self.options.timeout
        )
        if source is None:
            raise FileNotFoundError(self._path(source_name))
        target = self.bucket.blob(target_name)
        # A rewrite takes the metadata given for the target as a whole:
        # keep the source's, with the configured storage class.
        target.content_type = source.content_type
        target.cache_control = source.cache_control
        target.metadata = source.metadata
        target.storage_class = (
            self.options.storage_class or source.storage_class
        )
        token: str | None = None
        while True:
            token, _, _ = target.rewrite(
                source, token=token, timeout=self.options.timeout
            )
            if token is None:
                return

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy an object on the service (``rewrite``, any size).

        Args:
            source: Existing file path.
            destination: New file path.

        Raises:
            FileNotFoundError: The source object does not exist.
            IsADirectoryError: A folder is at ``destination``.
        """
        await self._refuse_directory(destination)
        await self._call(
            "copy",
            source,
            partial(
                self._copy_object,
                self._name(source),
                self._name(destination),
            ),
            transfer=True,
            missing=FileNotFoundError,
        )

    async def move_file(self, source: str, destination: str) -> None:
        """Move an object, or a whole folder by copying then deleting.

        Folder contents are copied concurrently; the source is deleted
        only after every copy succeeded.

        Args:
            source: Existing path.
            destination: New path.

        Raises:
            FileNotFoundError: Nothing exists at ``source``.
        """
        if await self.file_exists(source):
            await self.copy_file(source, destination)
            await self.delete_file(source)
            return
        if not await self.directory_exists(source):
            msg = f"Path not found: {source}"
            raise FileNotFoundError(msg)
        source_prefix = self._dir_name(source)
        target_prefix = self._dir_name(destination)
        names = await self._call(
            "list", source, partial(self._names, source_prefix)
        )
        await gather_limited(
            [
                partial(
                    self._call,
                    "copy",
                    source,
                    partial(
                        self._copy_object,
                        name,
                        target_prefix + name[len(source_prefix) :],
                    ),
                    transfer=True,
                )
                for name in names
            ]
        )
        await self._delete_all(source, names)
