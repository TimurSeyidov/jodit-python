"""Shared test fixtures."""

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from jcpy import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client bound to a fresh application instance.

    Yields:
        Client sending requests to the app in-process.
    """
    transport = ASGITransport(app=create_app())
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        yield http
