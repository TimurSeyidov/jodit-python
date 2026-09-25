"""WebDAV server (WsgiDAV on cheroot) in a child process, for tests.

A separate process keeps cheroot's shutdown noise (buffered writers
finalized after their sockets closed) out of the test run.

Run as ``python -m tests.webdav_server ROOT [digest]``: prints the port,
then serves until stdin closes.
"""

import base64
import contextlib
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

USER = "user"
PASSWORD = "secret"  # noqa: S105 - test server
TOKEN = "test-token"  # noqa: S105 - test server

type WsgiApp = Callable[[dict[str, object], object], Iterable[bytes]]


def _bearer(app: WsgiApp) -> WsgiApp:
    """Accept ``Authorization: Bearer <TOKEN>`` in front of WsgiDAV."""
    basic = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()

    def wrapped(
        environ: dict[str, object], start_response: object
    ) -> Iterable[bytes]:
        if environ.get("HTTP_AUTHORIZATION") == f"Bearer {TOKEN}":
            environ["HTTP_AUTHORIZATION"] = f"Basic {basic}"
        return app(environ, start_response)

    return wrapped


def main(root: str, digest: bool) -> None:
    """Serve ``root`` as ``/dav/`` until stdin closes.

    Args:
        root: Directory to share.
        digest: Ask for Digest instead of Basic authentication.
    """
    from cheroot import wsgi
    from wsgidav.wsgidav_app import WsgiDAVApp

    logging.disable(logging.WARNING)
    app = WsgiDAVApp(
        {
            "host": "127.0.0.1",
            "port": 0,
            "provider_mapping": {"/dav": root},
            "simple_dc": {
                "user_mapping": {"*": {USER: {"password": PASSWORD}}}
            },
            "http_authenticator": {
                "accept_basic": not digest,
                "accept_digest": digest,
                "default_to_digest": digest,
                "trusted_auth_header": None,
            },
            "verbose": 0,
            "logging": {"enable": False},
        }
    )
    server = wsgi.Server(("127.0.0.1", 0), _bearer(app))
    server.prepare()
    threading.Thread(target=server.serve, daemon=True).start()
    print(server.bind_addr[1], flush=True)
    sys.stdin.read()
    server.stop()


@contextlib.contextmanager
def serving(root: Path, *, digest: bool = False) -> Iterator[str]:
    """Serve ``root`` as ``/dav/`` for the duration of the block.

    Args:
        root: Directory to share.
        digest: Ask for Digest instead of Basic authentication.

    Yields:
        Base URL of the share, ending with ``/``.
    """
    arguments = [sys.executable, "-m", "tests.webdav_server", str(root)]
    if digest:
        arguments.append("digest")
    process = subprocess.Popen(  # noqa: S603 - fixed arguments
        arguments,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert process.stdout is not None
    assert process.stdin is not None
    try:
        port = int(process.stdout.readline())
        yield f"http://127.0.0.1:{port}/dav/"
    finally:
        process.stdin.close()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()


if __name__ == "__main__":
    main(sys.argv[1], digest="digest" in sys.argv[2:])
