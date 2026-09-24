"""Standalone entry point: ``jcpy`` / ``python -m jcpy.run``."""

import os

import uvicorn

DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - the service is meant to be exposed
DEFAULT_PORT = 8081
MAX_PORT = 65535


def get_port() -> int:
    """Read the listening port from the ``PORT`` environment variable.

    Returns:
        Port number, ``8081`` when ``PORT`` is not set.

    Raises:
        SystemExit: ``PORT`` is not an integer in the range 1-65535.
    """
    raw = os.environ.get("PORT", str(DEFAULT_PORT))
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 0 < port <= MAX_PORT:
        msg = "Invalid PORT. Must be a number between 1 and 65535."
        raise SystemExit(msg)
    return port


def main() -> None:
    """Serve the connector with uvicorn until interrupted.

    Listens on ``HOST`` (default ``0.0.0.0``) and ``PORT``
    (default ``8081``).
    """
    uvicorn.run(
        "jcpy.app:create_app",
        factory=True,
        host=os.environ.get("HOST", DEFAULT_HOST),
        port=get_port(),
    )


if __name__ == "__main__":
    main()
