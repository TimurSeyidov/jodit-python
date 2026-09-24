"""Application and router factories."""

from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import FastAPI

from jcpy.config.loader import load_config
from jcpy.connector import Connector

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import APIRouter
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from jcpy.types import AuthCallback, OriginPredicate

VERSION_HEADER = b"x-app-version"


def create_router(
    config_file: str | Path | None = None,
    *,
    check_authentication: AuthCallback | None = None,
    allowed_origins: OriginPredicate | None = None,
) -> APIRouter:
    """Build an isolated connector instance as a router.

    Every router owns its configuration and callbacks, so several
    instances can be mounted into one application under different
    prefixes.

    Args:
        config_file: JSON file overriding the defaults; when omitted
            the ``CONFIG`` and ``CONFIG_FILE`` environment variables are
            consulted.
        check_authentication: Resolves the role of the user per
            request; without it every request gets ``defaultRole``.
        allowed_origins: CORS origin predicate replacing the
            ``allowedOrigins`` list of the configuration.

    Returns:
        Router serving ``/ping``, ``/`` and ``/{action}``.

    Raises:
        ConfigError: The configuration cannot be read or is invalid.
    """
    connector = Connector(
        load_config(config_file),
        check_authentication=check_authentication,
        allowed_origins=allowed_origins,
    )
    return connector.build_router()


class _VersionHeaderMiddleware:
    """Add ``X-App-version`` to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.version = version("jodit-python").encode()

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_version(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (VERSION_HEADER, self.version),
                ]
            await send(message)

        await self.app(scope, receive, send_with_version)


def create_app(
    config_file: str | Path | None = None,
    *,
    check_authentication: AuthCallback | None = None,
    allowed_origins: OriginPredicate | None = None,
) -> FastAPI:
    """Build a standalone connector application.

    Args:
        config_file: JSON file overriding the defaults; when omitted
            the ``CONFIG`` and ``CONFIG_FILE`` environment variables are
            consulted.
        check_authentication: Resolves the role of the user per
            request; without it every request gets ``defaultRole``.
        allowed_origins: CORS origin predicate replacing the
            ``allowedOrigins`` list of the configuration.

    Returns:
        Application with the connector mounted at ``/`` and the
        ``X-App-version`` response header.

    Raises:
        ConfigError: The configuration cannot be read or is invalid.
    """
    app = FastAPI(title="Jodit Connector", version=version("jodit-python"))
    app.add_middleware(_VersionHeaderMiddleware)
    app.include_router(
        create_router(
            config_file,
            check_authentication=check_authentication,
            allowed_origins=allowed_origins,
        )
    )
    return app
