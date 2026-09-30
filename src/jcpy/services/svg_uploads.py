"""SVG uploads made safe before they are stored."""

from typing import TYPE_CHECKING

from anyio import to_thread

from jcpy.errors import HttpError
from jcpy.helpers.svg import InvalidSvgError, sanitize_svg

if TYPE_CHECKING:
    from jcpy.sources import Source


def needs_cleaning(source: Source, storage_path: str) -> bool:
    """Tell whether a file about to be stored is an SVG to clean.

    Args:
        source: Target source.
        storage_path: Path the file will be stored at.

    Returns:
        ``True`` for ``.svg`` names when ``sanitizeSvg`` is on.
    """
    return (
        source.config.sanitize_svg
        and source.get_extension(storage_path) == "svg"
    )


async def cleaned_svg(data: bytes) -> bytes:
    """Remove active content from an SVG upload.

    Args:
        data: Uploaded contents.

    Returns:
        The image without scripts or script-running links.

    Raises:
        HttpError: ``400`` when the data is not an SVG image that can be
            made safe.
    """
    try:
        return await to_thread.run_sync(sanitize_svg, data)
    except InvalidSvgError as error:
        raise HttpError.bad_request(str(error)) from None
