"""Shared test fixtures."""

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from jcpy import create_app
from jcpy.config.loader import build_config
from jcpy.connector import Connector
from jcpy.errors import HttpError
from jcpy.helpers.svg_icon import generate_icon
from jcpy.responses import success_response
from jcpy.v1 import ACTIONS

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.responses import Response

    from jcpy.acl import AccessControlProtocol, RulesProvider
    from jcpy.context import ActionContext, ActionHandler
    from jcpy.helpers.svg_icon import SvgGenerator
    from jcpy.types import AuthCallback, JsonObject, JsonValue, OriginPredicate

ENV_VARS = (
    "CONFIG",
    "CONFIG_FILE",
    "PORT",
    "HOST",
    "SOURCE_NAME",
    "SOURCE_ROOT",
    "SOURCE_BASEURL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test without connector environment variables."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


async def echo_action(context: ActionContext) -> Response:
    """Reply with what the pipeline passed to the handler.

    Args:
        context: Action context.

    Returns:
        Success envelope with role, action, parameters and file names.
    """
    return success_response(
        {
            "role": context.role,
            "action": context.params.action,
            "params": context.params.data,
            "files": [file.filename or "" for file in context.params.files],
        }
    )


async def failing_action(context: ActionContext) -> Response:
    """Fail with the error named by the ``kind`` parameter.

    Args:
        context: Action context.

    Raises:
        HttpError: ``kind=http``.
        RuntimeError: Any other ``kind``.
    """
    if context.params.get_str("kind", "") == "http":
        raise HttpError.forbidden("Access denied")
    msg = "Boom"
    raise RuntimeError(msg)


TEST_ACTIONS: Mapping[str, ActionHandler] = {
    **ACTIONS,
    "echo": echo_action,
    "fail": failing_action,
}

type ClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


def make_app(
    config: JsonObject | None = None,
    *,
    check_authentication: AuthCallback | None = None,
    allowed_origins: OriginPredicate | None = None,
    access_control: RulesProvider | None = None,
    access_control_instance: AccessControlProtocol | None = None,
    svg_generator: SvgGenerator = generate_icon,
    actions: Mapping[str, ActionHandler] = TEST_ACTIONS,
    prefix: str = "",
) -> FastAPI:
    """Build an application around one connector instance.

    Args:
        config: User configuration (JSON names).
        check_authentication: Authentication callback.
        allowed_origins: CORS origin predicate.
        access_control: Access rules provider.
        access_control_instance: Custom access control.
        svg_generator: Thumbnail icon renderer.
        actions: Action handlers.
        prefix: Mount point of the connector router.

    Returns:
        Application for in-process requests.
    """
    connector = Connector(
        build_config(config or {}),
        check_authentication=check_authentication,
        allowed_origins=allowed_origins,
        access_control=access_control,
        access_control_instance=access_control_instance,
        svg_generator=svg_generator,
        actions=actions,
    )
    app = FastAPI()
    app.include_router(connector.build_router(), prefix=prefix)
    return app


@asynccontextmanager
async def open_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Open an HTTP client bound to an application.

    Args:
        app: Application under test.

    Yields:
        Client sending requests to the app in-process.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        yield http


@pytest.fixture
def connector_client() -> ClientFactory:
    """Factory of clients for a connector with the test actions.

    Returns:
        Callable taking ``make_app`` arguments and returning an async
        context manager with the client.
    """

    def factory(
        config: JsonObject | None = None,
        *,
        check_authentication: AuthCallback | None = None,
        allowed_origins: OriginPredicate | None = None,
    ) -> AbstractAsyncContextManager[AsyncClient]:
        return open_client(
            make_app(
                config,
                check_authentication=check_authentication,
                allowed_origins=allowed_origins,
            )
        )

    return factory


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Client of the standalone application with default settings.

    Yields:
        Client sending requests to ``create_app()`` in-process.
    """
    async with open_client(create_app()) as http:
        yield http


BASEURL = "http://localhost:8081/files/test/"


def source_config(root: Path, **settings: JsonValue) -> JsonObject:
    """Configuration with one local source named ``test``.

    Args:
        root: Source root directory.
        settings: Extra global settings.

    Returns:
        User configuration.
    """
    return {
        "sources": {
            "test": {
                "title": "Test Files",
                "root": str(root),
                "baseurl": BASEURL,
            }
        },
        **settings,
    }


def write_file(root: Path, relative: str, contents: bytes | str = b"") -> Path:
    """Create a file with its parent directories.

    Args:
        root: Base directory.
        relative: File path below ``root``.
        contents: File contents.

    Returns:
        Created file.
    """
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = contents.encode() if isinstance(contents, str) else contents
    path.write_bytes(data)
    return path
