"""Uploads from a remote URL."""

import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

from jcpy.errors import HttpError
from jcpy.helpers import ssrf
from jcpy.helpers.js import node_basename, parse_bytes, sanitize_filename
from jcpy.helpers.urls import parse_url

if TYPE_CHECKING:
    from jcpy.context import ActionContext
    from jcpy.sources import Source


NOT_WHITELISTED = "File type is not in white list"


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """File stored from a URL.

    Attributes:
        name: Stored file name.
        is_image: Whether the extension is an image one.
    """

    name: str
    is_image: bool


async def _target_path(source: Source, directory: str, file_name: str) -> str:
    """Apply ``saveSameFileNameStrategy`` (no ``.`` for extensionless)."""
    target = posixpath.join(directory, file_name)
    try:
        taken = await source.storage.file_exists(source.storage_path(target))
    except Exception:
        taken = False
    if not taken:
        return target
    strategy = source.config.save_same_file_name_strategy or "addNumber"
    if strategy == "error":
        msg = f"File {file_name} already exists"
        raise HttpError.bad_request(msg)
    if strategy == "replace":
        return target
    extension = source.get_extension(file_name)
    stem = node_basename(file_name, f".{extension}")
    counter = 1
    while True:
        name = (
            f"{stem}-{counter}.{extension}"
            if extension
            else f"{stem}-{counter}"
        )
        target = posixpath.join(directory, name)
        counter += 1
        try:
            if not await source.storage.file_exists(
                source.storage_path(target)
            ):
                return target
        except Exception:
            return target


async def upload_from_url(
    context: ActionContext, source: Source, url: str, relative_path: str
) -> RemoteFile:
    """Download a file into a directory of a source.

    The name is the last segment of the URL path (decoded, sanitized),
    or ``downloaded-file``. Unless ``allowPrivateNetworkUploads`` is on,
    only public ``http``/``https`` hosts are contacted, redirects
    included. The stored file must have an allowed extension, fit
    ``maxUploadFileSize`` (the download stops as soon as it is
    exceeded) and pass ``FILE_UPLOAD`` for its extension.

    Args:
        context: Action context (role and access control).
        source: Source to store into.
        url: File URL.
        relative_path: Target directory relative to the source root.

    Returns:
        Stored file.

    Raises:
        HttpError: ``403`` without ``FILE_UPLOAD``, for private hosts,
            forbidden extensions or sizes; ``400`` for invalid URLs,
            failed downloads or a taken name with the ``error``
            strategy.
    """
    directory = await source.get_path(relative_path)
    await context.access.check_permission(
        context.role, "FILE_UPLOAD", directory
    )
    parsed = parse_url(url)
    if parsed is None:
        raise HttpError.bad_request("Invalid URL")
    file_name = (
        unquote(posixpath.basename(parsed.pathname)) or "downloaded-file"
    )
    # Never empty: "_" replaces unsafe parts and there is a fallback.
    safe_name = sanitize_filename(file_name, "_")

    config = source.config
    limit = (
        parse_bytes(config.max_upload_file_size) or 0
        if config.max_upload_file_size
        else None
    )
    try:
        contents = await ssrf.download(
            url,
            guard=not config.allow_private_network_uploads,
            limit=limit,
            network_timeout=config.timeout_limit,
        )
    except ssrf.DownloadTooLargeError:
        # The extension is checked before the size.
        if not source.is_safe_file(safe_name):
            raise HttpError.forbidden(NOT_WHITELISTED) from None
        raise

    target = await _target_path(source, directory, safe_name)
    storage_path = source.storage_path(target)
    # Check before writing: a rejected download must never overwrite
    # (and then remove) an existing file of the same name.
    if not source.is_safe_file(storage_path):
        raise HttpError.forbidden(NOT_WHITELISTED)
    await context.access.check_permission(
        context.role,
        "FILE_UPLOAD",
        source.get_root(),
        source.get_extension(target),
    )
    await source.storage.write(storage_path, contents)
    return RemoteFile(
        posixpath.basename(target), source.is_image(storage_path)
    )
