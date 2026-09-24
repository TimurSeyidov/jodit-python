"""Public type aliases shared across the connector."""

from collections.abc import Awaitable, Callable

from starlette.requests import Request

type JsonValue = (
    str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
)
"""Any value representable in JSON."""

type JsonObject = dict[str, JsonValue]
"""JSON object."""

type AuthCallback = Callable[[Request], str | Awaitable[str]]
"""Resolve the role of the user sending the request.

Raising an exception fails the request with an error response.
"""

type OriginPredicate = Callable[[str, Request], bool | Awaitable[bool]]
"""Decide whether a CORS origin is allowed for the request."""
