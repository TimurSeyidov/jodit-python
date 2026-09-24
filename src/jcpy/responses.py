"""Response envelopes: ``{"success": ..., "data": {...}}``."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from jcpy.types import JsonObject

SUCCESS_CODE = 220


def success_response(data: JsonObject) -> JSONResponse:
    """Build a successful action response.

    Args:
        data: Action payload; ``code`` defaults to ``220``.

    Returns:
        ``200`` response with ``{"success": true, "data": data}``.
    """
    return JSONResponse(
        {"success": True, "data": {"code": SUCCESS_CODE, **data}}
    )


def error_response(status_code: int, messages: list[str]) -> JSONResponse:
    """Build an error response.

    Args:
        status_code: HTTP status, repeated as ``data.code``.
        messages: Error messages.

    Returns:
        Response with ``{"success": false, "data": {"code", "messages"}}``.
    """
    return JSONResponse(
        {
            "success": False,
            "data": {"code": status_code, "messages": messages},
        },
        status_code=status_code,
    )


def internal_error_response(message: str) -> JSONResponse:
    """Build a ``500`` error response.

    Args:
        message: Error message.

    Returns:
        Error envelope with status ``500``.
    """
    return error_response(HTTPStatus.INTERNAL_SERVER_ERROR, [message])
