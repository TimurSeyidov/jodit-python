"""Role kept in a server-signed session, like PHP ``$_SESSION``.

The connector is mounted into an application that owns the session
middleware and the login routes. The login route below trusts its
argument and only stands in for a real sign-in.

Run from the repository root::

    SESSION_SECRET=change-me uv run python examples/session_auth.py
    curl -c cookies.txt "http://localhost:8081/login/editor"
    curl -b cookies.txt \\
        "http://localhost:8081/?action=permissions&source=uploads"
    curl -b cookies.txt "http://localhost:8081/logout"
"""

import os
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware

from jcpy import create_router

CONFIG = Path(__file__).parent / "config" / "roles.json"
SECRET = os.environ.get("SESSION_SECRET", "change-me")
SESSION_MAX_AGE = 24 * 60 * 60


# --8<-- [start:build]
def role_from_session(request: Request) -> str:
    """Read the role stored in the session.

    Args:
        request: Incoming request.

    Returns:
        Stored role, ``guest`` before login.
    """
    role = request.session.get("userRole")
    return role if isinstance(role, str) else "guest"


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Application with session routes and the connector at ``/``.
    """
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware, secret_key=SECRET, max_age=SESSION_MAX_AGE
    )

    @app.get("/login/{role}")
    def login(
        request: Request, role: Literal["guest", "editor", "admin"]
    ) -> dict[str, str]:
        request.session["userRole"] = role
        return {"role": role}

    @app.get("/logout")
    def logout(request: Request) -> dict[str, str]:
        request.session.clear()
        return {"role": "guest"}

    @app.get("/whoami")
    def whoami(request: Request) -> dict[str, str]:
        return {"role": role_from_session(request)}

    # Own routes first: the connector serves every other /{action}.
    app.include_router(
        create_router(CONFIG, check_authentication=role_from_session)
    )
    return app


# --8<-- [end:build]

if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
