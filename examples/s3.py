"""Files stored in an S3 bucket.

Credentials come from the usual AWS sources (environment variables,
shared config, instance role). For MinIO or another S3-compatible
service set ``endpoint`` and ``forcePathStyle`` in the ``s3`` block.

Run from the repository root::

    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \\
        uv run python examples/s3.py
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI

from jcpy import create_app

CONFIG = Path(__file__).parent / "config" / "s3.json"


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Connector application backed by S3.
    """
    return create_app(CONFIG)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
