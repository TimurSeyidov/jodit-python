"""Two independent connectors in one application.

``/public`` lets everyone browse and nothing else; ``/admin`` needs the
``X-Admin-Token`` header. Each instance has its own configuration,
authentication and caches.

Run from the repository root::

    ADMIN_TOKEN=secret uv run python examples/multi_instance.py
    curl "http://localhost:8081/public/files"
    curl -H "X-Admin-Token: secret" "http://localhost:8081/admin/files"
"""

import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

from jcpy import create_router

CONFIG_DIR = Path(__file__).parent / "config"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me")


def public_role(_request: Request) -> str:
    """Treat every visitor of the public connector as a guest.

    Returns:
        ``guest``.
    """
    return "guest"


def admin_role(request: Request) -> str:
    """Grant ``admin`` to requests with the right token.

    Args:
        request: Incoming request.

    Returns:
        ``admin`` or ``anonymous``.
    """
    token = request.headers.get("x-admin-token", "")
    if secrets.compare_digest(token.encode(), ADMIN_TOKEN.encode()):
        return "admin"
    return "anonymous"


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Application serving both connectors.
    """
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(
        create_router(
            CONFIG_DIR / "public.json", check_authentication=public_role
        ),
        prefix="/public",
    )
    app.include_router(
        create_router(
            CONFIG_DIR / "admin.json", check_authentication=admin_role
        ),
        prefix="/admin",
    )
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
