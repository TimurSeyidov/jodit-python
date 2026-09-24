"""Storage adapter for AWS S3 and S3-compatible object stores.

Folders are emulated like the S3 console does: a zero-byte object whose
key ends with ``/`` marks an explicitly created folder, and any key with
a ``/`` implies its parent folders.
"""

import mimetypes
from io import BytesIO
from typing import TYPE_CHECKING, Any

import boto3
from anyio import to_thread
from botocore.config import Config
from botocore.exceptions import ClientError

from jcpy.storage.base import StatEntry

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator, Iterator
    from datetime import datetime

    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

    from jcpy.config.models import S3Options

DEFAULT_REGION = "us-east-1"
DELETE_BATCH_SIZE = 1000
_NOT_FOUND = frozenset({"404", "NoSuchKey", "NotFound"})


def normalize_s3_path(path: str) -> str:
    """Normalize a storage path to an S3 key fragment.

    Args:
        path: Path with any separators.

    Returns:
        Path with ``/`` only, no empty or ``.`` segments; ``""`` for the
        root.
    """
    segments = path.replace("\\", "/").split("/")
    return "/".join(part for part in segments if part and part != ".")


def build_object_key(prefix: str, path: str) -> str:
    """Build the object key of a storage path.

    Args:
        prefix: Key prefix acting as the source root.
        path: Storage path.

    Returns:
        Object key.
    """
    normalized_prefix = normalize_s3_path(prefix)
    normalized_path = normalize_s3_path(path)
    if not normalized_prefix:
        return normalized_path
    if not normalized_path:
        return normalized_prefix
    return f"{normalized_prefix}/{normalized_path}"


def strip_object_prefix(prefix: str, key: str) -> str:
    """Turn an object key back into a storage path.

    Args:
        prefix: Key prefix acting as the source root.
        key: Object key.

    Returns:
        Storage path; keys outside the prefix are only normalized.
    """
    normalized_prefix = normalize_s3_path(prefix)
    if not normalized_prefix:
        return normalize_s3_path(key)
    if key == normalized_prefix:
        return ""
    with_slash = f"{normalized_prefix}/"
    if key.startswith(with_slash):
        return normalize_s3_path(key[len(with_slash) :])
    return normalize_s3_path(key)


def default_public_base_url(options: S3Options) -> str:
    """Build the bucket URL files are publicly served from.

    Args:
        options: S3 settings.

    Returns:
        Path-style URL for ``forcePathStyle`` endpoints, virtual-host
        URL otherwise; AWS URLs use the region. The prefix is appended.
    """
    prefix = normalize_s3_path(options.prefix or "")
    suffix = f"/{prefix}" if prefix else ""
    if options.endpoint is not None:
        endpoint = options.endpoint.rstrip("/")
        if options.force_path_style:
            return f"{endpoint}/{options.bucket}{suffix}"
        scheme, _, rest = endpoint.partition("://")
        host = rest.split("/", 1)[0]
        return f"{scheme}://{options.bucket}.{host}{suffix}"
    region = options.region or DEFAULT_REGION
    return f"https://{options.bucket}.s3.{region}.amazonaws.com{suffix}"


def create_client(options: S3Options) -> S3Client:
    """Create a boto3 client for the settings.

    Args:
        options: S3 settings; without ``credentials`` the AWS default
            chain (environment, profile, instance role) is used.

    Returns:
        S3 client.
    """
    kwargs: dict[str, Any] = {"region_name": options.region or DEFAULT_REGION}
    if options.endpoint is not None:
        kwargs["endpoint_url"] = options.endpoint
    if options.force_path_style is not None:
        kwargs["config"] = Config(
            s3={
                "addressing_style": (
                    "path" if options.force_path_style else "virtual"
                )
            }
        )
    if options.credentials is not None:
        kwargs["aws_access_key_id"] = options.credentials.access_key_id
        kwargs["aws_secret_access_key"] = options.credentials.secret_access_key
        if options.credentials.session_token is not None:
            kwargs["aws_session_token"] = options.credentials.session_token
    return boto3.client("s3", **kwargs)


def _is_not_found(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _NOT_FOUND or status == 404


def _milliseconds(moment: datetime | None) -> float:
    return moment.timestamp() * 1000 if moment is not None else 0


def _content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class S3StorageAdapter:
    """Storage adapter for one bucket (and optional key prefix).

    Object ACLs are never touched: make the prefix readable with a
    bucket policy or serve it through a CDN.

    Args:
        options: S3 settings.
        client: Pre-configured client (tests, shared clients).
    """

    def __init__(
        self, options: S3Options, client: S3Client | None = None
    ) -> None:
        self.bucket = options.bucket
        self.prefix = normalize_s3_path(options.prefix or "")
        self.client = client or create_client(options)
        self.public_base_url = (
            options.public_base_url or default_public_base_url(options)
        ).rstrip("/")

    def _key(self, path: str) -> str:
        return build_object_key(self.prefix, path)

    def _dir_key(self, path: str) -> str:
        key = self._key(path)
        return f"{key}/" if key else ""

    def _path(self, key: str) -> str:
        return strip_object_prefix(self.prefix, key)

    def public_url(self, path: str) -> str:
        """Public URL of a stored file.

        Args:
            path: Storage path.

        Returns:
            ``publicBaseUrl`` (or the bucket URL) joined with the path.
        """
        normalized = normalize_s3_path(path)
        if not normalized:
            return self.public_base_url
        return f"{self.public_base_url}/{normalized}"

    async def write(self, path: str, contents: bytes) -> None:
        """Upload an object (multipart for large bodies).

        Args:
            path: File path.
            contents: File contents.
        """
        key = self._key(path)
        await to_thread.run_sync(
            lambda: self.client.upload_fileobj(
                BytesIO(contents),
                self.bucket,
                key,
                ExtraArgs={"ContentType": _content_type(key)},
            )
        )

    async def read(self, path: str) -> bytes:
        """Download an object.

        Args:
            path: File path.

        Returns:
            Object body.
        """

        def get() -> bytes:
            response = self.client.get_object(
                Bucket=self.bucket, Key=self._key(path)
            )
            return response["Body"].read()

        return await to_thread.run_sync(get)

    async def delete_file(self, path: str) -> None:
        """Delete an object; a missing one is not an error.

        Args:
            path: File path.
        """
        await to_thread.run_sync(
            lambda: self.client.delete_object(
                Bucket=self.bucket, Key=self._key(path)
            )
        )

    async def create_directory(self, path: str) -> None:
        """Create a folder marker object.

        Args:
            path: Directory path; the root needs no marker.
        """
        if not normalize_s3_path(path):
            return
        await to_thread.run_sync(
            lambda: self.client.put_object(
                Bucket=self.bucket, Key=self._dir_key(path), Body=b""
            )
        )

    async def stat(self, path: str) -> StatEntry:
        """Describe an object, or a folder (explicit or implied).

        Args:
            path: Entry path.

        Returns:
            File metadata or a directory entry.

        Raises:
            FileNotFoundError: Neither an object nor a folder exists.
        """
        normalized = normalize_s3_path(path)
        if not normalized:
            return StatEntry("", is_file=False, last_modified_ms=0)
        try:
            head = await to_thread.run_sync(
                lambda: self.client.head_object(
                    Bucket=self.bucket, Key=self._key(path)
                )
            )
        except ClientError as error:
            if not _is_not_found(error):
                raise
        else:
            return StatEntry(
                normalized,
                is_file=True,
                size=head.get("ContentLength", 0),
                last_modified_ms=_milliseconds(head.get("LastModified")),
            )
        if await self.directory_exists(path):
            return StatEntry(normalized, is_file=False, last_modified_ms=0)
        msg = f"Path not found: {path}"
        raise FileNotFoundError(msg)

    def _pages(
        self, prefix: str, *, delimiter: bool
    ) -> Iterator[dict[str, Any]]:
        paginator = self.client.get_paginator("list_objects_v2")
        arguments: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
        if delimiter:
            arguments["Delimiter"] = "/"
        for page in paginator.paginate(**arguments):
            yield dict(page)

    def _scan(self, path: str, deep: bool) -> builtins.list[StatEntry]:
        dir_key = self._dir_key(path)
        base = self._path(dir_key)
        seen: set[str] = set()
        entries: builtins.list[StatEntry] = []

        def add_directory(directory: str, modified: float = 0) -> None:
            if directory and directory not in seen:
                seen.add(directory)
                entries.append(
                    StatEntry(
                        directory, is_file=False, last_modified_ms=modified
                    )
                )

        for page in self._pages(dir_key, delimiter=not deep):
            for common in page.get("CommonPrefixes", []):
                prefix = common.get("Prefix")
                if prefix and prefix != dir_key:
                    add_directory(self._path(prefix))
            for item in page.get("Contents", []):
                key = item.get("Key")
                if not key or key == dir_key:
                    continue
                if key.endswith("/"):
                    add_directory(
                        self._path(key),
                        _milliseconds(item.get("LastModified")),
                    )
                    continue
                file_path = self._path(key)
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
                        size=item.get("Size", 0),
                        last_modified_ms=_milliseconds(
                            item.get("LastModified")
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
        for entry in await to_thread.run_sync(self._scan, path, deep):
            yield entry

    async def delete_directory(self, path: str) -> None:
        """Delete every object below a folder, in batches of 1000.

        Args:
            path: Directory path.
        """
        dir_key = self._dir_key(path)

        def delete() -> None:
            while True:
                page = self.client.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=dir_key,
                    MaxKeys=DELETE_BATCH_SIZE,
                )
                keys: builtins.list[ObjectIdentifierTypeDef] = [
                    {"Key": item["Key"]}
                    for item in page.get("Contents", [])
                    if "Key" in item
                ]
                if not keys:
                    return
                self.client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": keys, "Quiet": True}
                )
                if not page.get("IsTruncated"):
                    return

        await to_thread.run_sync(delete)

    async def file_exists(self, path: str) -> bool:
        """Tell whether an object exists.

        Args:
            path: File path.

        Returns:
            ``True`` when the object exists; always ``False`` for the root.
        """
        if not normalize_s3_path(path):
            return False
        try:
            await to_thread.run_sync(
                lambda: self.client.head_object(
                    Bucket=self.bucket, Key=self._key(path)
                )
            )
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True

    async def directory_exists(self, path: str) -> bool:
        """Tell whether a folder exists (marker or any key below it).

        Args:
            path: Directory path.

        Returns:
            ``True`` for the root and non-empty prefixes.
        """
        if not normalize_s3_path(path):
            return True
        page = await to_thread.run_sync(
            lambda: self.client.list_objects_v2(
                Bucket=self.bucket, Prefix=self._dir_key(path), MaxKeys=1
            )
        )
        return page.get("KeyCount", 0) > 0

    def _put_marker(self, key: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=b"")

    def _copy_object(self, source_key: str, target_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": source_key},
            Key=target_key,
        )

    async def copy_file(self, source: str, destination: str) -> None:
        """Copy an object.

        Args:
            source: Existing file path.
            destination: New file path.
        """
        await to_thread.run_sync(
            self._copy_object, self._key(source), self._key(destination)
        )

    async def move_file(self, source: str, destination: str) -> None:
        """Move an object, or a whole folder by copying then deleting.

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

        from_key = self._dir_key(source)
        to_key = self._dir_key(destination)
        async for entry in self.list(source, deep=True):
            source_key = self._key(entry.path)
            target_key = to_key + source_key[len(from_key) :]
            if entry.is_directory:
                await to_thread.run_sync(self._put_marker, f"{target_key}/")
            else:
                await to_thread.run_sync(
                    self._copy_object, source_key, target_key
                )
        await self.create_directory(destination)
        await self.delete_directory(source)
