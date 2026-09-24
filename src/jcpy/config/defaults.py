"""Default values that are not plain literals."""

import os
from pathlib import Path

EXTENSIONS = (
    "jpg",
    "png",
    "gif",
    "jpeg",
    "bmp",
    "ico",
    "jpeg",
    "psd",
    "svg",
    "ttf",
    "tif",
    "ai",
    "txt",
    "css",
    "html",
    "js",
    "htm",
    "ini",
    "xml",
    "zip",
    "rar",
    "7z",
    "gz",
    "tar",
    "pps",
    "ppt",
    "pptx",
    "odp",
    "xls",
    "xlsx",
    "csv",
    "doc",
    "docx",
    "pdf",
    "rtf",
    "avi",
    "flv",
    "3gp",
    "mov",
    "mkv",
    "mp4",
    "wmv",
    "webp",
)

IMAGE_EXTENSIONS = ("jpg", "png", "gif", "jpeg", "bmp", "svg", "ico", "webp")


def default_source() -> dict[str, str]:
    """Build the source used when the configuration defines none.

    Reads ``SOURCE_NAME`` (title), ``SOURCE_ROOT`` and
    ``SOURCE_BASEURL``, falling back to ``./files`` served from
    ``http://localhost:$PORT/files/``.

    Returns:
        Source settings keyed by their JSON names.
    """
    port = os.environ.get("PORT", "8081")
    root = os.environ.get("SOURCE_ROOT")
    return {
        "name": "default",
        "title": os.environ.get("SOURCE_NAME", "Test Files"),
        "root": str(Path(root).resolve() if root else Path.cwd() / "files"),
        "baseurl": os.environ.get(
            "SOURCE_BASEURL", f"http://localhost:{port}/files/"
        ),
    }
