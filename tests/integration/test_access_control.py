"""Access control in the request pipeline."""

import asyncio
from typing import TYPE_CHECKING

import pytest
from starlette.responses import JSONResponse

from jcpy.acl import AccessControl
from jcpy.config.models import AccessControlRule
from tests.conftest import (
    make_app,
    open_client,
    source_config,
    write_file,
)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.types import JsonObject
    from tests.conftest import ClientFactory

DENIED = {
    "success": False,
    "data": {"code": 403, "messages": ["Access denied"]},
}


def rules(*items: JsonObject) -> JsonObject:
    return {"accessControl": list(items), "defaultRole": "guest"}


async def test_no_rules_allow_everything(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.get("/echo")

    assert response.status_code == 200


async def test_denied_role(connector_client: ClientFactory) -> None:
    async with connector_client(
        rules({"role": "guest", "ECHO": False})
    ) as http:
        response = await http.get("/echo")

    assert response.status_code == 403
    assert response.json() == DENIED


async def test_permission_is_checked_before_action_lookup(
    connector_client: ClientFactory,
) -> None:
    async with connector_client(rules({"role": "*", "NOPE": False})) as http:
        denied = await http.get("/nope")
        missing = await http.get("/other")

    assert denied.status_code == 403
    assert missing.status_code == 404


async def test_allowed_role(connector_client: ClientFactory) -> None:
    config = {
        "accessControl": [{"role": "admin", "ECHO": True}],
        "defaultRole": "admin",
    }
    async with connector_client(config) as http:
        response = await http.get("/echo")

    assert response.status_code == 200


async def test_path_rules_use_request_path(
    connector_client: ClientFactory,
) -> None:
    config = rules(
        {"role": "guest", "ECHO": True},
        {"role": "guest", "path": "/private", "ECHO": False},
    )
    async with connector_client(config) as http:
        public = await http.get("/echo", params={"path": "/"})
        private = await http.get("/echo", params={"path": "/private"})
        nested = await http.post("/echo", json={"path": "/private/a"})

    assert public.status_code == 200
    assert private.status_code == 403
    assert nested.status_code == 403


async def test_wildcard_role(connector_client: ClientFactory) -> None:
    async with connector_client(rules({"role": "*", "ECHO": False})) as http:
        response = await http.get("/echo")

    assert response.status_code == 403


async def test_role_from_authentication(
    connector_client: ClientFactory,
) -> None:
    def auth(request: Request) -> str:
        return request.headers.get("x-role", "guest")

    config = rules(
        {"role": "*", "ECHO": False}, {"role": "admin", "ECHO": True}
    )
    async with connector_client(config, check_authentication=auth) as http:
        guest = await http.get("/echo")
        admin = await http.get("/echo", headers={"X-Role": "admin"})

    assert guest.status_code == 403
    assert admin.status_code == 200


async def test_async_rules_provider() -> None:
    async def load() -> list[AccessControlRule]:
        await asyncio.sleep(0.01)
        return [
            AccessControlRule.model_validate({"role": "guest", "ECHO": False})
        ]

    async with open_client(make_app(access_control=load)) as http:
        response = await http.get("/echo")

    assert response.status_code == 403


async def test_sync_provider_replaces_config_rules() -> None:
    def load() -> list[AccessControlRule]:
        return [AccessControlRule.model_validate({"ECHO": True})]

    app = make_app(rules({"ECHO": False}), access_control=load)
    async with open_client(app) as http:
        response = await http.get("/echo")

    assert response.status_code == 200


async def test_custom_instance() -> None:
    class ReadOnly(AccessControl):
        async def is_allow(
            self,
            role: str,
            action: str,
            path: str = "/",
            file_extension: str = "*",
        ) -> bool:
            return action == "echo"

    app = make_app(access_control_instance=ReadOnly([]))
    async with open_client(app) as http:
        allowed = await http.get("/echo")
        denied = await http.get("/fail")

    assert allowed.status_code == 200
    assert denied.status_code == 403


async def test_handlers_receive_the_access_control() -> None:
    instance = AccessControl([])
    seen: list[object] = []

    async def spy(context: ActionContext) -> Response:
        seen.append(context.access)
        return JSONResponse({})

    app = make_app(access_control_instance=instance, actions={"spy": spy})
    async with open_client(app) as http:
        await http.get("/spy")

    assert seen == [instance]


@pytest.mark.parametrize(
    "path",
    ["/private", "private", "./private", "/public/../private", "//private"],
)
@pytest.mark.parametrize("action", ["files", "folders"])
async def test_path_rule_holds_for_every_spelling(
    connector_client: ClientFactory, tmp_path: Path, path: str, action: str
) -> None:
    write_file(tmp_path, "private/secret.txt", "s")
    (tmp_path / "public").mkdir()
    config: JsonObject = {
        **source_config(tmp_path),
        "accessControl": [
            {"path": "/private", "FILES": False, "FOLDERS": False}
        ],
    }

    async with connector_client(config) as http:
        response = await http.get(f"/{action}", params={"path": path})

    assert response.status_code == 403
    assert "secret.txt" not in response.text
