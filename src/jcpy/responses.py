"""Response envelopes: ``{"success": ..., "data": {...}}``."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from jcpy.types import JsonObject

SUCCESS_CODE = 220


class JsonResponse(JSONResponse):
    """JSON response labelled ``application/json; charset=utf-8``.

    The body is compact UTF-8 JSON.
    """

    media_type = "application/json; charset=utf-8"


def success_response(data: JsonObject) -> JsonResponse:
    """Build a successful action response.

    Args:
        data: Action payload; ``code`` defaults to ``220``.

    Returns:
        ``200`` response with ``{"success": true, "data": data}``.
    """
    return JsonResponse(
        {"success": True, "data": {"code": SUCCESS_CODE, **data}}
    )


def error_response(status_code: int, messages: list[str]) -> JsonResponse:
    """Build an error response.

    Args:
        status_code: HTTP status, repeated as ``data.code``.
        messages: Error messages.

    Returns:
        Response with ``{"success": false, "data": {"code", "messages"}}``.
    """
    return JsonResponse(
        {
            "success": False,
            "data": {"code": status_code, "messages": messages},
        },
        status_code=status_code,
    )


def internal_error_response(message: str) -> JsonResponse:
    """Build a ``500`` error response.

    Args:
        message: Error message.

    Returns:
        Error envelope with status ``500``.
    """
    return error_response(HTTPStatus.INTERNAL_SERVER_ERROR, [message])
