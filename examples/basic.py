"""Standalone connector configured from a JSON file.

Run from the repository root::

    uv run python examples/basic.py
    curl "http://localhost:8081/?action=files"
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI

from jcpy import create_app

CONFIG = Path(__file__).parent / "config" / "basic.json"


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Connector application; every request gets ``defaultRole``.
    """
    return create_app(CONFIG)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
