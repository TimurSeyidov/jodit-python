"""Thumbnails of listed files and folders."""

import posixpath
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from anyio import to_thread
from PIL import Image

from jcpy.helpers.js import slugify

if TYPE_CHECKING:
    from jcpy.sources import Source
    from jcpy.storage.base import StatEntry

_JPEG_MODES = frozenset({"RGB", "L", "CMYK"})


@dataclass(slots=True)
class ThumbCounter:
    """Number of thumbnails generated during one listing.

    Attributes:
        count: Thumbnails generated so far.
    """

    count: int = 0


def render_thumbnail(
    contents: bytes, extension: str, size: int, quality: int
) -> bytes:
    """Scale an image to fit a square box, keeping its format.

    Args:
        contents: Source image.
        extension: Lower-cased extension choosing the output format:
            ``webp``, ``png`` and ``gif`` keep theirs, anything else
            becomes JPEG.
        size: Box side in pixels; smaller images are not enlarged.
        quality: JPEG/WebP quality.

    Returns:
        Encoded thumbnail.
    """
    with Image.open(BytesIO(contents)) as source:
        image = source.copy()
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    output = BytesIO()
    match extension:
        case "webp":
            image.save(output, "WEBP", quality=quality)
        case "png":
            image.save(output, "PNG")
        case "gif":
            image.save(output, "GIF")
        case _:
            if image.mode not in _JPEG_MODES:
                image = image.convert("RGB")
            image.save(output, "JPEG", quality=quality)
    return output.getvalue()


async def _is_directory(source: Source, pathname: str) -> bool:
    try:
        return await source.storage.directory_exists(source.relative(pathname))
    except Exception:
        return False


async def make_thumb(
    source: Source, entry: StatEntry, counter: ThumbCounter
) -> str:
    """Return the thumbnail of a listed entry, creating it when missing.

    Thumbnails live in ``thumbFolderName`` next to the entry and are
    named after its slug: images keep their extension, folders and
    other files get an SVG icon.

    Args:
        source: Source of the entry.
        entry: Listed entry (path relative to the source root).
        counter: Incremented for every thumbnail generated.

    Returns:
        Absolute path of the thumbnail, or of the entry itself when no
        thumbnail can be made (SVG images, unreadable images, icons
        disabled).
    """
    config = source.config
    root = source.get_root()
    full_path = posixpath.join(root, entry.path)
    directory = posixpath.dirname(full_path)
    thumb_directory = posixpath.join(directory, config.thumb_folder_name)

    if not await _is_directory(source, thumb_directory):
        await source.storage.create_directory(source.relative(thumb_directory))

    extension = (
        "svg"
        if entry.is_directory or not source.is_image(entry.path)
        else source.get_extension(entry.path)
    )
    base = posixpath.basename(entry.path)
    suffix = f".{extension}"
    if base.endswith(suffix) and base != suffix:
        base = base[: -len(suffix)]
    thumb_path = posixpath.join(thumb_directory, f"{slugify(base)}{suffix}")
    thumb_relative = source.relative(thumb_path)

    if await source.storage.file_exists(thumb_relative):
        return thumb_path
    if source.get_extension(entry.path) == "svg":
        return full_path

    counter.count += 1

    if source.is_image(entry.path):
        try:
            contents = await source.storage.read(entry.path)
            thumbnail = await to_thread.run_sync(
                render_thumbnail,
                contents,
                extension,
                config.thumb_size,
                config.quality,
            )
            await source.storage.write(thumb_relative, thumbnail)
        except Exception:
            return full_path
    elif config.generate_svg_thumbs:
        icon = source.svg_generator(
            entry, config.svg_thumb_width, config.svg_thumb_height
        )
        await source.storage.write(thumb_relative, icon.encode())
    else:
        return full_path

    return thumb_path
