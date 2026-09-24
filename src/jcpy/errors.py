"""Errors that map to connector error responses."""

from http import HTTPStatus


class HttpError(Exception):
    """Error answered with its HTTP status and the error envelope.

    Args:
        status_code: HTTP status of the response, also used as
            ``data.code``.
        message: Error message; also the only entry of
            ``data.messages`` when ``messages`` is not given.
        messages: Explicit list for ``data.messages``.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        messages: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.messages = messages if messages is not None else [message]

    @classmethod
    def bad_request(
        cls, message: str, messages: list[str] | None = None
    ) -> HttpError:
        """Build a ``400 Bad Request`` error.

        Args:
            message: Error message.
            messages: Explicit list for ``data.messages``.

        Returns:
            The error.
        """
        return cls(HTTPStatus.BAD_REQUEST, message, messages)

    @classmethod
    def forbidden(cls, message: str) -> HttpError:
        """Build a ``403 Forbidden`` error.

        Args:
            message: Error message.

        Returns:
            The error.
        """
        return cls(HTTPStatus.FORBIDDEN, message)

    @classmethod
    def not_found(cls, message: str) -> HttpError:
        """Build a ``404 Not Found`` error.

        Args:
            message: Error message.

        Returns:
            The error.
        """
        return cls(HTTPStatus.NOT_FOUND, message)

    @classmethod
    def method_not_allowed(cls, message: str) -> HttpError:
        """Build a ``405 Method Not Allowed`` error.

        Args:
            message: Error message.

        Returns:
            The error.
        """
        return cls(HTTPStatus.METHOD_NOT_ALLOWED, message)


class ConfigError(Exception):
    """Connector configuration cannot be loaded or is invalid."""
