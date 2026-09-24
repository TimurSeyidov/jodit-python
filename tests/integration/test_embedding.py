"""Several connector instances in one application."""

import asyncio
import json
import random
from typing import TYPE_CHECKING

from fastapi import FastAPI

from jcpy import create_app, create_router
from tests.conftest import open_client

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from jcpy.types import AuthCallback


def _config(tmp_path: Path, name: str, *, can_list: bool) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / f"{name}.txt").write_text(name)
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "accessControl": [{"role": name, "FILES": can_list}],
                "sources": {
                    name: {
                        "title": name,
                        "root": str(root),
                        "baseurl": f"http://localhost/{name}/",
                    }
                },
            }
        )
    )
    return path


async def test_instances_stay_isolated_under_concurrency(
    tmp_path: Path,
) -> None:
    seen: dict[str, list[str]] = {"a": [], "b": []}

    def auth_for(name: str) -> AuthCallback:
        async def auth(request: Request) -> str:
            # Interleave the two instances' requests.
            await asyncio.sleep(random.random() / 100)  # noqa: S311
            seen[name].append(request.url.path)
            return name

        return auth

    app = FastAPI()
    for name, can_list in (("a", True), ("b", False)):
        app.include_router(
            create_router(
                _config(tmp_path, name, can_list=can_list),
                check_authentication=auth_for(name),
            ),
            prefix=f"/{name}",
        )

    async with open_client(app) as http:
        responses = await asyncio.gather(
            *(
                http.get(f"/{name}/{action}")
                for _ in range(20)
                for name in ("a", "b")
                for action in ("files", "permissions")
            )
        )

    by_path: dict[str, set[str]] = {}
    for response in responses:
        body = response.json()
        by_path.setdefault(response.url.path, set()).add(
            json.dumps(body, sort_keys=True)
        )

    # Every request of a path got the same answer.
    assert all(len(answers) == 1 for answers in by_path.values())
    a_files = json.loads(next(iter(by_path["/a/files"])))
    b_files = json.loads(next(iter(by_path["/b/files"])))
    a_perms = json.loads(next(iter(by_path["/a/permissions"])))
    b_perms = json.loads(next(iter(by_path["/b/permissions"])))
    (source,) = a_files["data"]["sources"]
    assert source["name"] == "a"
    assert [item["file"] for item in source["files"]] == ["a.txt"]
    assert b_files["data"]["code"] == 403
    assert a_perms["data"]["permissions"]["allowFiles"] is True
    assert b_perms["data"]["permissions"]["allowFiles"] is False
    assert all(path.startswith("/a/") for path in seen["a"])
    assert all(path.startswith("/b/") for path in seen["b"])
    assert len(seen["a"]) == len(seen["b"]) == 40


async def test_builtin_docs_are_not_served() -> None:
    async with open_client(create_app()) as http:
        responses = [
            await http.get(path)
            for path in ("/docs", "/redoc", "/openapi.json")
        ]

    for response, action in zip(
        responses, ("docs", "redoc", "openapi.json"), strict=True
    ):
        assert response.status_code == 404
        assert response.json()["data"]["messages"] == [
            f'Action "{action}" not found'
        ]
