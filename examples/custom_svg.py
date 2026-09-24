"""Custom SVG thumbnails for folders and non-image files.

Run from the repository root::

    uv run python examples/custom_svg.py
    curl "http://localhost:8081/?action=files"
"""

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import uvicorn
from fastapi import FastAPI

from jcpy import create_app

if TYPE_CHECKING:
    from jcpy.storage.base import StatEntry

CONFIG = Path(__file__).parent / "config" / "svg.json"
COLORS = {
    ".pdf": "#e74c3c",
    ".doc": "#3498db",
    ".docx": "#3498db",
    ".txt": "#95a5a6",
    ".zip": "#f39c12",
    ".tar": "#f39c12",
    ".gz": "#f39c12",
    ".json": "#9b59b6",
    ".xml": "#9b59b6",
}
MAX_NAME = 12


def colored_icon(entry: StatEntry, width: int, height: int) -> str:
    """Render a tile colored by file type with the extension and name.

    Args:
        entry: Folder or file the icon stands for.
        width: Icon width in pixels.
        height: Icon height in pixels.

    Returns:
        SVG document.
    """
    path = PurePosixPath(entry.path)
    ext = path.suffix.lower()
    color = "#2ecc71" if entry.is_directory else COLORS.get(ext, "#7f8c8d")
    label = "DIR" if entry.is_directory else ext.removeprefix(".").upper()
    name = path.name
    if len(name) > MAX_NAME:
        name = f"{name[:MAX_NAME]}..."
    # File names are user input: escape them inside the markup.
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 100 100" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="100" height="100" fill="{color}" rx="8"/>'
        '<text x="50" y="40" text-anchor="middle" fill="white" '
        'font-family="Arial" font-size="20" font-weight="bold">'
        f"{escape(label)}</text>"
        '<text x="50" y="70" text-anchor="middle" fill="white" '
        'font-family="Arial" font-size="10" opacity="0.8">'
        f"{escape(name)}</text></svg>"
    )


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Connector application with the custom icon generator.
    """
    return create_app(CONFIG, svg_generator=colored_icon)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
