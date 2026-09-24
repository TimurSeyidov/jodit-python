"""Standalone entry point: ``jcpy`` / ``python -m jcpy.run``."""

import os

import uvicorn

DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - the service is meant to be exposed
DEFAULT_PORT = 8081
MAX_PORT = 65535


def get_port() -> int:
    """Read the listening port from ``PORT``."""
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
    """Run the connector with uvicorn."""
    uvicorn.run(
        "jcpy.app:create_app",
        factory=True,
        host=os.environ.get("HOST", DEFAULT_HOST),
        port=get_port(),
    )


if __name__ == "__main__":
    main()
