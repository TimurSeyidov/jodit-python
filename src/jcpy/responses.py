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


def error_response(
    status_code: int, messages: list[str], *, http_status: bool = True
) -> JsonResponse:
    """Build an error response.

    Args:
        status_code: Error code of ``data.code``.
        messages: Error messages.
        http_status: Send ``status_code`` as the HTTP status; ``200``
            otherwise, as the PHP connector does (see
            ``errorHttpStatus``).

    Returns:
        Response with ``{"success": false, "data": {"code", "messages"}}``.
    """
    return JsonResponse(
        {
            "success": False,
            "data": {"code": status_code, "messages": messages},
        },
        status_code=status_code if http_status else HTTPStatus.OK,
    )


def internal_error_response(
    message: str, *, http_status: bool = True
) -> JsonResponse:
    """Build a ``500`` error response.

    Args:
        message: Error message.
        http_status: Send ``500`` as the HTTP status; ``200``
            otherwise.

    Returns:
        Error envelope with code ``500``.
    """
    return error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR, [message], http_status=http_status
    )
