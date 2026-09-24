"""Control server running jodit-nodejs tests against jodit-python.

``POST /__create`` takes a connector configuration (JSON) and answers
``{"id": ...}``; the connector then serves ``/i/<id>/...``.
``DELETE /__destroy/<id>`` drops it. Used by ``test-server.ts``.

Usage:
    python scripts/parity/server.py PORT
"""

import json
import sys
import tempfile
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from starlette.responses import JSONResponse

from jcpy import create_app

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

_apps: dict[str, ASGIApp] = {}
_ids = count(1)
_configs = Path(tempfile.mkdtemp(prefix="jcpy-parity-"))


async def _read(receive: Receive) -> bytes:
    body = bytearray()
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            return bytes(body)


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    """Create, drop and dispatch to connector instances."""
    if scope["type"] != "http":
        return
    path: str = scope["path"]
    if path == "/__create":
        config = json.loads(await _read(receive))
        instance = str(next(_ids))
        config_file = _configs / f"{instance}.json"
        config_file.write_text(json.dumps(config), "utf-8")
        try:
            _apps[instance] = create_app(config_file)
        except Exception as error:
            response = JSONResponse({"error": str(error)}, status_code=400)
        else:
            response = JSONResponse({"id": instance})
        await response(scope, receive, send)
        return
    if path.startswith("/__destroy/"):
        _apps.pop(path.removeprefix("/__destroy/"), None)
        await JSONResponse({})(scope, receive, send)
        return
    parts = path.split("/", 3)
    is_instance = len(parts) > 2 and parts[1] == "i"
    target = _apps.get(parts[2]) if is_instance else None
    if target is None:
        await JSONResponse({"error": "no instance"}, status_code=404)(
            scope, receive, send
        )
        return
    prefix = f"/i/{parts[2]}"
    inner = dict(scope)
    inner["path"] = path.removeprefix(prefix) or "/"
    inner["raw_path"] = inner["path"].encode()
    await target(inner, receive, send)


if __name__ == "__main__":
    uvicorn.run(
        app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning"
    )
