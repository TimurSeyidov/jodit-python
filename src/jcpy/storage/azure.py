"""Storage adapter for Azure Blob Storage.

Folders are emulated as in the ``s3`` adapter: a zero-byte blob whose
name ends with ``/`` marks an explicitly created folder, and any name
with a ``/`` implies its parent folders.
"""

import contextlib
import mimetypes
import time
from functools import partial
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from anyio import to_thread
from azure.core.exceptions import (
    AzureError,
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.storage.blob import (
    ContainerClient,
    ContentSettings,
    StandardBlobTier,
)

from jcpy.helpers.concurrency import gather_limited
from jcpy.storage.base import CHUNK_SIZE, FileWasNotFoundError, StatEntry
from jcpy.storage.keys import build_key, normalize_key, strip_key_prefix
from jcpy.storage.threads import TransferThreads

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator, Callable, Iterator
    from datetime import datetime
    from typing import BinaryIO

    from azure.storage.blob import BlobClient, StorageStreamDownloader

    from jcpy.config.models import AzureOptions

PART_SIZE = 4 * 1024 * 1024
"""Bytes per request when large blobs are downloaded or uploaded."""

DELETE_BATCH_SIZE = 256
"""Blobs deleted per batch request (the service limit)."""

COPY_POLL_SECONDS = 0.5
"""Pause between checks of a pending server-side copy."""

COPY_TIMEOUT_SECONDS = 600
"""Longest wait for a server-side copy to finish."""


class AzureStorageError(OSError):
    """An Azure Storage request failed.

    The message holds the service error code and the storage path, never
    the account URL or a SAS token.

    Args:
        operation: What was attempted.
        path: Storage path.
        error: SDK error.
    """

    def __init__(self, operation: str, path: str, error: AzureError) -> None:
        code = getattr(error, "error_code", None)
        status = getattr(error, "status_code", None)
        reason = " ".join(str(part) for part in (status, code) if part)
        super().__init__(
            f"{operation} /{path} failed: {reason or type(error).__name__}"
        )
        self.error_code = code


def _milliseconds(moment: datetime | None) -> float:
    return moment.timestamp() * 1000 if moment is not None else 0


def _content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def create_container_client(options: AzureOptions) -> ContainerClient:
    """Create a container client for the settings.

    Args:
        options: Azure settings; with ``accountUrl`` and neither
            ``accountKey`` nor ``sasToken`` the Azure default credential
            chain (environment, managed identity, ``az login``) is used.

    Returns:
        Container client.
    """
    kwargs: dict[str, Any] = {
        "connection_timeout": options.connect_timeout,
        "read_timeout": options.read_timeout,
        "retry_total": options.max_attempts - 1,
        "max_single_get_size": PART_SIZE,
        "max_chunk_get_size": PART_SIZE,
        "max_single_put_size": PART_SIZE,
        "max_block_size": PART_SIZE,
    }
    if options.connection_string is not None:
        return ContainerClient.from_connection_string(
            options.connection_string, options.container, **kwargs
        )
    account_url = cast("str", options.account_url)  # set: see the model
    credential: Any
    if options.account_key is not None:
        account = account_name(account_url)
        credential = {
            "account_name": account,
            "account_key": options.account_key,
        }
    elif options.sas_token is not None:
        credential = options.sas_token
    else:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
    return ContainerClient(
        account_url, options.container, credential=credential, **kwargs
    )


def account_name(account_url: str) -> str:
    """Storage account named by an account URL.

    Args:
        account_url: ``https://<account>.blob.core.windows.net`` or a
            path-style URL such as Azurite's ``http://host:10000/<account>``.

    Returns:
        The account name.
    """
    parts = urlsplit(account_url)
    first_segment = parts.path.strip("/").split("/", 1)[0]
    return first_segment or (parts.hostname or "").split(".", 1)[0]


def batch_requests_work(client: ContainerClient) -> bool:
    """Tell whether batch requests address blobs correctly.

    The SDK knows a path-style URL (account in the path, as in Azurite)
    only on ``localhost`` and ``127.0.0.1``; on any other host, such as
    ``http://azurite:10000/devstoreaccount1``, batch sub-requests lose
    the account and fail.

    Args:
        client: Container client.

    Returns:
        ``False`` for path-style URLs the SDK does not recognize.
    """
    segments = [s for s in urlsplit(client.url).path.split("/") if s]
    path_style = len(segments) > 1
    return not path_style or bool(getattr(client, "_is_localhost", False))


class _FullReader:
    """File wrapper completing short reads.

    The SDK sends what one ``read(n)`` returns as ``n`` bytes of a
    request whose length is already announced.
    """

    def __init__(self, file: BinaryIO) -> None:
        self.file = file

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self.file.read()
        parts: list[bytes] = []
        missing = size
        while missing and (part := self.file.read(missing)):
            parts.append(part)
            missing -= len(part)
        return b"".join(parts)


class AzureStorageAdapter:
    """Storage adapter for one container (and optional name prefix).

    Uploads are atomic (a blob appears when its blocks are committed);
    copies run on the service when it can verify the source, and are
    streamed through the connector otherwise.

    Args:
        options: Azure settings.
        client: Pre-configured container client (tests, shared clients).
    """

    def __init__(
        self, options: AzureOptions, client: ContainerClient | None = None
    ) -> None:
        self.options = options
        self.prefix = normalize_key(options.prefix or "")
        self.client = client or create_container_client(options)
        self._transfers = TransferThreads()
        self._batches = batch_requests_work(self.client)
        self._tier = (
            StandardBlobTier(options.access_tier)
            if options.access_tier is not None
            else None
        )
        self.public_base_url = (
            options.public_base_url
            or f"{self.client.url.split('?', 1)[0].rstrip('/')}"
            + (f"/{self.prefix}" if self.prefix else "")
        ).rstrip("/")

    def _name(self, path: str) -> str:
        return build_key(self.prefix, path)

    def _dir_name(self, path: str) -> str:
        name = self._name(path)
        return f"{name}/" if name else ""

    def _path(self, name: str) -> str:
        return strip_key_prefix(self.prefix, name)

    def public_url(self, path: str) -> str:
        """Public URL of a stored file.

        Args:
            path: Storage path.

        Returns:
            ``publicBaseUrl`` (or the container URL) joined with the path.
        """
        normalized = normalize_key(path)
        if not normalized:
            return self.public_base_url
        return f"{self.public_base_url}/{normalized}"

    async def _call[T](
        self, operation: str, path: str, func: Callable[[], T]
    ) -> T:
        """Run a blocking SDK call, hiding URLs from its errors."""
        try:
            return await to_thread.run_sync(func)
        except ResourceNotFoundError:
            raise
        except AzureError as error:
            raise AzureStorageError(operation, path, error) from None

    async def _transfer[T](
        self, operation: str, path: str, func: Callable[[], T]
    ) -> T:
        try:
            return await self._transfers.run(func)
        except ResourceNotFoundError:
            raise
        except AzureError as error:
            raise AzureStorageError(operation, path, error) from None

    def _upload(
        self, path: str, data: object, length: int | None = None
    ) -> None:
        name = self._name(path)
        self.client.upload_blob(
            name,
            data,  # type: ignore[arg-type]
            length=length,
            overwrite=True,
            content_settings=ContentSettings(
                content_type=_content_type(name),
                cache_control=self.options.cache_control,
            ),
            standard_blob_tier=self._tier,
            max_concurrency=self.options.max_concurrency,
        )

    async def _refuse_directory(self, path: str) -> None:
        """Keep a blob from shadowing a folder of the same name."""
        if normalize_key(path) and await self.directory_exists(path):
            raise IsADirectoryError(path)

    async def write(self, path: str, contents: bytes) -> None:
        """Upload a blob.

        Args:
            path: File path.
            contents: File contents.

        Raises:
            IsADirectoryError: A folder is at ``path``.
        """
        await self._refuse_directory(path)
        await self._transfer(
            "write", path, partial(self._upload, path, contents)
        )

    async def write_file(self, path: str, file: BinaryIO) -> None:
        """Upload a blob from a readable binary file, in blocks.

        Args:
            path: File path.
            file: Source positioned at the start of the contents.

        Raises:
            IsADirectoryError: A folder is at ``path``.
        """
        await self._refuse_directory(path)
        start = file.tell()
        length = await to_thread.run_sync(file.seek, 0, 2) - start
        await to_thread.run_sync(file.seek, start)
        reader = _FullReader(file)
        await self._transfer(
            "write", path, partial(self._upload, path, reader, length)
        )

    def _download(self, path: str) -> StorageStreamDownloader[bytes]:
        try:
            return self.client.get_blob_client(self._name(path)).download_blob(
                max_concurrency=1
            )
        except ResourceNotFoundError:
            raise FileWasNotFoundError(path) from None

    async def iter_file(self, path: str) -> AsyncIterator[bytes]:
        """Download a blob in chunks (at most 4 MB held at once).

        Args:
            path: File path.

        Yields:
            Chunks of at most ``CHUNK_SIZE`` bytes.

        Raises:
            FileWasNotFoundError: The blob does not exist.
        """
        stream = await self._call("read", path, partial(self._download, path))
        while chunk := await self._transfer(
            "read", path, partial(stream.read, CHUNK_SIZE)
        ):
            yield chunk

    async def read(self, path: str) -> bytes:
        """Download a whole blob.

        Args:
            path: File path.

        Returns:
            File contents.

        Raises:
            FileWasNotFoundError: The blob does not exist.
        """

        def read() -> bytes:
            return self._download(path).readall()

        return await self._transfer("read", path, read)

    async def delete_file(self, path: str) -> None:
        """Delete a blob; a missing blob is not an error.

        Args:
            path: File path.

        Raises:
            IsADirectoryError: ``path`` is a folder.
        """
        try:
            await self._call(
                "delete",
                path,
                partial(self.client.delete_blob, self._name(path)),
            )
        except ResourceNotFoundError:
            if normalize_key(path) and await self.directory_exists(path):
                raise IsADirectoryError(path) from None

    async def create_directory(self, path: str) -> None:
        """Create a folder marker blob.

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
        await self._call(
            "create folder",
            path,
            partial(
                self.client.upload_blob,
                self._dir_name(path),
                b"",
                overwrite=True,
            ),
        )

    def _blob_names(self, prefix: str) -> Iterator[str]:
        for blob in self.client.list_blobs(name_starts_with=prefix):
            yield blob.name

    def _delete_all(self, names: builtins.list[str]) -> None:
        if not self._batches:
            for name in names:
                with contextlib.suppress(ResourceNotFoundError):
                    self.client.delete_blob(name)
            return
        for start in range(0, len(names), DELETE_BATCH_SIZE):
            batch = names[start : start + DELETE_BATCH_SIZE]
            failed = [
                response
                for response in self.client.delete_blobs(
                    *batch, raise_on_any_failure=False
                )
                if response.status_code not in {202, 404}
            ]
            if failed:
                msg = (
                    f"{len(failed)} blob(s) could not be deleted, "
                    f"status {failed[0].status_code}"
                )
                raise OSError(msg)

    async def delete_directory(self, path: str) -> None:
        """Delete every blob below a folder, 256 per batch request.

        Path-style URLs the SDK cannot batch for delete blob by blob.

        A file at ``path`` is deleted too; the root itself stays.

        Args:
            path: Directory path.

        Raises:
            OSError: Some blobs could not be deleted.
        """
        if normalize_key(path) and await self.file_exists(path):
            await self.delete_file(path)
            return
        prefix = self._dir_name(path) or (
            f"{self.prefix}/" if self.prefix else ""
        )

        def delete() -> None:
            self._delete_all(list(self._blob_names(prefix)))

        await self._call("delete folder", path, delete)

    async def stat(self, path: str) -> StatEntry:
        """Describe a blob, or a folder (explicit or implied).

        Args:
            path: Entry path.

        Returns:
            File metadata or a directory entry.

        Raises:
            FileNotFoundError: Neither a blob nor a folder exists.
        """
        normalized = normalize_key(path)
        if not normalized:
            return StatEntry("", is_file=False, last_modified_ms=0)
        try:
            properties = await self._call(
                "stat",
                path,
                partial(
                    self.client.get_blob_client(
                        self._name(path)
                    ).get_blob_properties
                ),
            )
        except ResourceNotFoundError:
            pass
        else:
            return StatEntry(
                normalized,
                is_file=True,
                size=properties.size,
                last_modified_ms=_milliseconds(properties.last_modified),
            )
        if await self.directory_exists(path):
            return StatEntry(normalized, is_file=False, last_modified_ms=0)
        msg = f"Path not found: {path}"
        raise FileNotFoundError(msg)

    def _scan(self, path: str, deep: bool) -> builtins.list[StatEntry]:
        dir_name = self._dir_name(path) or (
            f"{self.prefix}/" if self.prefix else ""
        )
        base = self._path(dir_name)
        seen: set[str] = set()
        entries: builtins.list[StatEntry] = []

        def add_directory(directory: str) -> None:
            if directory and directory not in seen:
                seen.add(directory)
                entries.append(
                    StatEntry(directory, is_file=False, last_modified_ms=0)
                )

        items = (
            self.client.list_blobs(name_starts_with=dir_name)
            if deep
            else self.client.walk_blobs(name_starts_with=dir_name)
        )
        for item in items:
            name = item.name
            if not name or name == dir_name:
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
                    size=getattr(item, "size", None),
                    last_modified_ms=_milliseconds(
                        getattr(item, "last_modified", None)
                    ),
                )
            )
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
        """Tell whether a blob exists.

        Args:
            path: File path.

        Returns:
            ``True`` when the blob exists; always ``False`` for the root.
        """
        if not normalize_key(path):
            return False
        return await self._call(
            "stat",
            path,
            self.client.get_blob_client(self._name(path)).exists,
        )

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a folder exists (marker or any blob below it).

        Args:
            path: Directory path.

        Returns:
            ``True`` for the root and non-empty prefixes.
        """
        if not normalize_key(path):
            return True

        def any_blob() -> bool:
            pages = self.client.list_blobs(
                name_starts_with=self._dir_name(path), results_per_page=1
            ).by_page()
            return any(True for _ in next(pages, []))

        return await self._call("stat", path, any_blob)

    def _copy_blob(self, source_name: str, target_name: str) -> None:
        source = self.client.get_blob_client(source_name)
        target = self.client.get_blob_client(target_name)
        try:
            target.start_copy_from_url(
                source.url, standard_blob_tier=self._tier
            )
        except HttpResponseError as error:
            if getattr(error, "error_code", None) != "CannotVerifyCopySource":
                raise
            # The service cannot read the source with this credential
            # (Entra ID): stream the copy through the connector.
            self._stream_copy(source, target_name)
            return
        self._wait_for_copy(target)

    def _stream_copy(self, source: BlobClient, target_name: str) -> None:
        properties = source.get_blob_properties()
        downloader = source.download_blob(max_concurrency=1)
        self.client.upload_blob(
            target_name,
            downloader.chunks(),
            length=properties.size,
            overwrite=True,
            content_settings=properties.content_settings,
            standard_blob_tier=self._tier,
            max_concurrency=self.options.max_concurrency,
        )

    @staticmethod
    def _wait_for_copy(target: BlobClient) -> None:
        deadline = time.monotonic() + COPY_TIMEOUT_SECONDS
        while True:
            copy = target.get_blob_properties().copy
            if copy.status in {None, "success"}:
                return
            if copy.status != "pending" or time.monotonic() > deadline:
                msg = f"Copy ended with status {copy.status}"
                raise OSError(msg)
            time.sleep(COPY_POLL_SECONDS)

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy a blob (on the service when it can read the source).

        Args:
            source: Existing file path.
            destination: New file path.

        Raises:
            FileNotFoundError: The source blob does not exist.
            IsADirectoryError: A folder is at ``destination``.
        """
        await self._refuse_directory(destination)
        try:
            await self._transfer(
                "copy",
                source,
                partial(
                    self._copy_blob,
                    self._name(source),
                    self._name(destination),
                ),
            )
        except ResourceNotFoundError:
            raise FileNotFoundError(source) from None

    async def move_file(self, source: str, destination: str) -> None:
        """Move a blob, or a whole folder by copying then deleting.

        Folder contents are copied concurrently; the source is deleted
        only after every copy succeeded.

        Args:
            source: Existing path.
            destination: New path.

        Raises:
            FileNotFoundError: Nothing exists at ``source``.
            IsADirectoryError: A folder is at ``destination``.
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
            "list", source, lambda: list(self._blob_names(source_prefix))
        )
        jobs = [
            partial(
                self._transfer,
                "copy",
                source,
                partial(
                    self._copy_blob,
                    name,
                    target_prefix + name[len(source_prefix) :],
                ),
            )
            for name in names
        ]
        await gather_limited(jobs)
        await self._call(
            "delete folder", source, partial(self._delete_all, names)
        )
