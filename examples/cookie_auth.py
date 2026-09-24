"""Role taken from a cookie on every request.

The cookie is set by the client, so this only suits trusted
environments; sign it or keep the role server side (see
``session_auth.py``) in production.

Run from the repository root::

    uv run python examples/cookie_auth.py
    curl "http://localhost:8081/?action=permissions&source=uploads"
    curl -H "Cookie: userRole=editor" \\
        "http://localhost:8081/?action=permissions&source=uploads"
    curl -X POST -H "Cookie: userRole=admin" -F "files[0]=@README.md" \\
        "http://localhost:8081/?action=fileUpload&source=uploads"
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

from jcpy import create_app

CONFIG = Path(__file__).parent / "config" / "roles.json"
ROLE_COOKIE = "userRole"


def role_from_cookie(request: Request) -> str:
    """Read the role of the user from the ``userRole`` cookie.

    Args:
        request: Incoming request.

    Returns:
        Cookie value, ``guest`` when the cookie is missing.
    """
    return request.cookies.get(ROLE_COOKIE) or "guest"


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Connector application authenticating by cookie.
    """
    return create_app(CONFIG, check_authentication=role_from_cookie)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
