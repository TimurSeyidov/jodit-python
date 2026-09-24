"""Image editing: resize, crop, save, load."""

import base64
import posixpath
from io import BytesIO
from typing import TYPE_CHECKING

from anyio import to_thread
from PIL import Image, UnidentifiedImageError

from jcpy.errors import HttpError
from jcpy.helpers.js import (
    node_basename,
    node_extname,
    sanitize_filename,
    slugify,
)
from jcpy.sources import PATH_NOT_FOUND, is_path_within_root

if TYPE_CHECKING:
    from collections.abc import Callable

    from jcpy.context import ActionContext
    from jcpy.sources import Source

UNSUPPORTED_FORMAT = "Input buffer contains unsupported image format"
BAD_EXTRACT_AREA = "extract_area: bad extract area"
_JPEG_QUALITY = 80

MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
}


class ImageError(ValueError):
    """Image data cannot be processed."""


def _open(contents: bytes) -> tuple[Image.Image, str]:
    """Decode an image; return it with its format name (``JPEG`` ...)."""
    try:
        with Image.open(BytesIO(contents)) as image:
            return image.copy(), image.format or "PNG"
    except (UnidentifiedImageError, OSError) as error:
        raise ImageError(UNSUPPORTED_FORMAT) from error


def _encode(image: Image.Image, image_format: str) -> bytes:
    """Encode in the source format, like sharp's ``toBuffer``."""
    output = BytesIO()
    if image_format == "JPEG":
        # Decoded JPEGs are always in a mode JPEG can store.
        image.save(output, image_format, quality=_JPEG_QUALITY)
    else:
        image.save(output, image_format)
    return output.getvalue()


def resize_bytes(contents: bytes, width: int, height: int) -> bytes:
    """Scale an image to exactly ``width`` x ``height``.

    Args:
        contents: Source image.
        width: Target width.
        height: Target height.

    Returns:
        Image in the source format.

    Raises:
        ImageError: The data is not a supported image.
    """
    image, image_format = _open(contents)
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    return _encode(resized, image_format)


def crop_bytes(
    contents: bytes, x: int, y: int, width: int, height: int
) -> bytes:
    """Cut a region out of an image.

    Args:
        contents: Source image.
        x: Left offset.
        y: Top offset.
        width: Region width.
        height: Region height.

    Returns:
        Image in the source format.

    Raises:
        ImageError: The data is not a supported image or the region
            does not fit inside it.
    """
    image, image_format = _open(contents)
    if x + width > image.width or y + height > image.height:
        raise ImageError(BAD_EXTRACT_AREA)
    return _encode(image.crop((x, y, x + width, y + height)), image_format)


def detect_format(contents: bytes) -> str | None:
    """Detect the format of image bytes.

    Args:
        contents: Candidate image.

    Returns:
        Lower-cased format such as ``jpeg`` or ``png``; ``None`` when
        the bytes are not a decodable image.
    """
    try:
        with Image.open(BytesIO(contents)) as image:
            image.verify()
            return (image.format or "").lower() or None
    except Exception:
        return None


async def _thumb_candidates(source: Source, storage_path: str) -> set[str]:
    extension = source.get_extension(storage_path)
    base = node_basename(storage_path, f".{extension}")
    folder = posixpath.join(
        posixpath.dirname(storage_path), source.config.thumb_folder_name
    )
    return {
        posixpath.normpath(posixpath.join(folder, f"{name}.{extension}"))
        for name in (slugify(base), base)
    }


async def remove_thumb(source: Source, storage_path: str) -> None:
    """Delete cached thumbnails of a file so they are regenerated.

    Both the slugified name used by listings and the raw name (used by
    other connectors sharing the folder) are removed. Failures are
    ignored.

    Args:
        source: Source of the file.
        storage_path: File path relative to the source root.
    """
    for thumb in await _thumb_candidates(source, storage_path):
        try:
            if await source.storage.file_exists(thumb):
                await source.storage.delete_file(thumb)
        except Exception:  # noqa: S112 - best effort cleanup
            continue


async def _replace(source: Source, storage_path: str, contents: bytes) -> None:
    """Overwrite a file through a temporary copy."""
    temporary = f"{storage_path}.tmp"
    await source.storage.write(temporary, contents)
    await source.storage.delete_file(storage_path)
    await source.storage.move_file(temporary, storage_path)


async def _existing_image(
    context: ActionContext,
    source: Source,
    action: str,
    name: str,
    relative_path: str,
) -> tuple[str, str]:
    """Resolve the edited image; return its directory and path."""
    directory = await source.get_path(relative_path)
    await context.access.check_permission(context.role, action, directory)
    image_path = await source.validate_path(posixpath.join(directory, name))
    if not is_path_within_root(image_path, directory):
        raise HttpError.not_found(PATH_NOT_FOUND)
    try:
        stat = await source.storage.stat(source.storage_path(image_path))
    except Exception:
        raise HttpError.not_found("File not exists") from None
    if not stat.is_file:
        raise HttpError.not_found("File not exists")
    return directory, image_path


async def _edit(
    context: ActionContext,
    source: Source,
    action: str,
    name: str,
    new_name: str,
    relative_path: str,
    transform: Callable[[bytes], bytes],
) -> str:
    directory, image_path = await _existing_image(
        context, source, action, name, relative_path
    )
    destination = image_path
    if new_name:
        new_name = sanitize_filename(new_name, "_")
        extension = node_extname(name)
        if node_extname(new_name) != extension:
            new_name += extension
        destination = await source.validate_path(
            posixpath.join(directory, new_name)
        )
        await context.access.check_permission(
            context.role, action, destination
        )

    image_storage = source.storage_path(image_path)
    destination_storage = source.storage_path(destination)
    verb = "resize" if action == "IMAGE_RESIZE" else "crop"
    try:
        contents = await source.storage.read(image_storage)
        edited = await to_thread.run_sync(transform, contents)
        if destination == image_path:
            await _replace(source, image_storage, edited)
        else:
            await source.storage.write(destination_storage, edited)
    except Exception as error:
        msg = f"Unable to {verb} image: {error}"
        raise HttpError.bad_request(msg) from None
    await remove_thumb(source, destination_storage)
    return destination_storage


async def resize_image(
    context: ActionContext,
    source: Source,
    name: str,
    box: dict[str, int],
    new_name: str,
    relative_path: str,
) -> str:
    """Scale an image to ``box`` (``w`` x ``h``, aspect not kept).

    Args:
        context: Action context (role and access control).
        source: Source holding the image.
        name: Image name in the current directory.
        box: Target ``w`` and ``h``.
        new_name: Save under this name (extension of ``name`` kept);
            overwrite ``name`` when empty.
        relative_path: Directory relative to the source root.

    Returns:
        Storage path of the written image.

    Raises:
        HttpError: ``403`` without ``IMAGE_RESIZE``, ``404`` for a
            missing image or a name leaving the directory, ``400`` when
            the image cannot be processed.
    """
    return await _edit(
        context,
        source,
        "IMAGE_RESIZE",
        name,
        new_name,
        relative_path,
        lambda contents: resize_bytes(contents, box["w"], box["h"]),
    )


async def crop_image(
    context: ActionContext,
    source: Source,
    name: str,
    box: dict[str, int],
    new_name: str,
    relative_path: str,
) -> str:
    """Cut ``box`` (``x``, ``y``, ``w``, ``h``) out of an image.

    Args:
        context: Action context (role and access control).
        source: Source holding the image.
        name: Image name in the current directory.
        box: Region to keep.
        new_name: Save under this name (extension of ``name`` kept);
            overwrite ``name`` when empty.
        relative_path: Directory relative to the source root.

    Returns:
        Storage path of the written image.

    Raises:
        HttpError: ``403`` without ``IMAGE_CROP``, ``404`` for a
            missing image or a name leaving the directory, ``400`` when
            the image cannot be processed or the region does not fit.
    """
    return await _edit(
        context,
        source,
        "IMAGE_CROP",
        name,
        new_name,
        relative_path,
        lambda contents: crop_bytes(
            contents, box["x"], box["y"], box["w"], box["h"]
        ),
    )


async def save_image(
    context: ActionContext,
    source: Source,
    contents: bytes,
    name: str,
    new_name: str,
    relative_path: str,
) -> str:
    """Store image bytes produced by the client-side image editor.

    The target is ``new_name`` (trimmed) or, when empty, ``name``; a
    target without extension takes the one of ``name`` or of the
    detected format. Stale thumbnails of the target are removed.

    Args:
        context: Action context (role and access control).
        source: Source to store into.
        contents: Edited image.
        name: Original image name.
        new_name: "Save as" name.
        relative_path: Directory relative to the source root.

    Returns:
        Storage path of the saved image.

    Raises:
        HttpError: ``403`` without ``IMAGE_SAVE`` or for a name whose
            extension is not allowed, ``400`` for data that
            is not an image, a missing name or a failed write, ``404``
            for a name leaving the directory.
    """
    directory = await source.get_path(relative_path)
    await context.access.check_permission(
        context.role, "IMAGE_SAVE", directory
    )

    image_format = await to_thread.run_sync(detect_format, contents)
    if image_format is None:
        raise HttpError.bad_request("Provided data is not a valid image")

    target = new_name.strip() or name
    if not target:
        raise HttpError.bad_request('Either "name" or "newname" is required')
    safe_name = sanitize_filename(target, "_")
    if not node_extname(safe_name):
        safe_name += node_extname(name) or f".{image_format}"
    # Image data under any name (shell.php, page.html) must not slip past
    # the "extensions" list that uploads obey.
    if not source.is_safe_file(safe_name):
        raise HttpError.forbidden("File type is not in white list")

    # A sanitized name is a single path segment, so it stays inside.
    destination = await source.validate_path(
        posixpath.join(directory, safe_name)
    )
    await context.access.check_permission(
        context.role, "IMAGE_SAVE", destination
    )

    storage_path = source.storage_path(destination)
    try:
        try:
            exists = await source.storage.file_exists(storage_path)
        except Exception:
            exists = False
        if exists:
            await _replace(source, storage_path, contents)
        else:
            await source.storage.write(storage_path, contents)
    except Exception as error:
        msg = f"Unable to save image: {error}"
        raise HttpError.bad_request(msg) from None

    await remove_thumb(source, storage_path)
    return storage_path


async def load_image(
    context: ActionContext, source: Source, name: str, relative_path: str
) -> tuple[str, str]:
    """Read an image as a base64 data URL.

    Args:
        context: Action context (role and access control).
        source: Source holding the image.
        name: Image name in the current directory.
        relative_path: Directory relative to the source root.

    Returns:
        Data URL (MIME type by extension) and the image file name.

    Raises:
        HttpError: ``403`` without ``IMAGE_LOAD``, ``404`` for a
            missing image or a name leaving the directory.
    """
    _, image_path = await _existing_image(
        context, source, "IMAGE_LOAD", name, relative_path
    )
    try:
        contents = await source.storage.read(source.storage_path(image_path))
    except Exception:
        raise HttpError.not_found("File not exists") from None
    mime = MIME_BY_EXTENSION.get(
        node_extname(name).lower(), "application/octet-stream"
    )
    encoded = base64.b64encode(contents).decode()
    return f"data:{mime};base64,{encoded}", node_basename(name)
