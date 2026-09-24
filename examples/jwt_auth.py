"""Role taken from a signed JWT in the ``Authorization`` header.

Tokens are HS256-signed with ``JWT_SECRET`` and must carry ``role``
and ``exp`` claims. Requests without a token are guests; a bad token
is answered with ``401``.

Run from the repository root (prints demo tokens)::

    JWT_SECRET=$(openssl rand -hex 32) uv run python examples/jwt_auth.py
    curl -H "Authorization: Bearer <token>" \\
        "http://localhost:8081/?action=permissions&source=uploads"
"""

import os
import time
from http import HTTPStatus
from pathlib import Path

import jwt
import uvicorn
from fastapi import FastAPI, Request

from jcpy import HttpError, create_app

CONFIG = Path(__file__).parent / "config" / "roles.json"
SECRET = os.environ.get("JWT_SECRET", "change-me-to-a-long-random-secret")
ALGORITHM = "HS256"
TOKEN_LIFETIME = 3600


# --8<-- [start:build]
def make_token(
    role: str, username: str, lifetime: int = TOKEN_LIFETIME
) -> str:
    """Issue a token, as a login endpoint would.

    Args:
        role: Role of the user.
        username: Name of the user.
        lifetime: Seconds until the token expires.

    Returns:
        Signed token.
    """
    payload = {
        "role": role,
        "username": username,
        "exp": int(time.time()) + lifetime,
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def role_from_jwt(request: Request) -> str:
    """Verify the bearer token and read the role from it.

    Args:
        request: Incoming request.

    Returns:
        ``role`` claim of the token, ``guest`` without a token.

    Raises:
        HttpError: ``401`` for a malformed, forged or expired token.
    """
    header = request.headers.get("authorization")
    if not header:
        return "guest"
    scheme, _, token = header.partition(" ")
    unauthorized = HttpError(
        HTTPStatus.UNAUTHORIZED, "Invalid or expired token"
    )
    if scheme.lower() != "bearer" or not token:
        raise unauthorized
    try:
        payload = jwt.decode(
            token,
            SECRET,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "role"]},
        )
    except jwt.InvalidTokenError as error:
        raise unauthorized from error
    role = payload["role"]
    if not isinstance(role, str):
        raise unauthorized
    return role


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Connector application authenticating by JWT.
    """
    return create_app(CONFIG, check_authentication=role_from_jwt)


# --8<-- [end:build]

if __name__ == "__main__":
    for demo_role in ("editor", "admin"):
        print(f"{demo_role}: {make_token(demo_role, demo_role)}")
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
