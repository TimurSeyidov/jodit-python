"""Programs in examples/ work as their docstrings describe."""

import importlib.util
import time
from pathlib import Path
from typing import TYPE_CHECKING

import jwt
import pytest

from jcpy.storage.base import StatEntry
from tests.conftest import open_client

if TYPE_CHECKING:
    from types import ModuleType

    from httpx import Response

SECRET = "change-me-to-a-long-random-secret"  # noqa: S105 - demo default
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"example_{name}", EXAMPLES / f"{name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the relative source roots of the examples in tmp_path."""
    for folder in (
        "files/uploads",
        "files/public",
        "files/private",
        "files/shared",
        "files/tenants/acme",
    ):
        (tmp_path / folder).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)


def _names(response: Response) -> list[str]:
    (source,) = response.json()["data"]["sources"]
    return [item["file"] for item in source["files"]]


def _upload(response: Response) -> bool:
    return bool(response.json()["data"]["permissions"]["allowFileUpload"])


async def _can_upload(module: ModuleType, headers: dict[str, str]) -> bool:
    async with open_client(module.build_app()) as http:
        response = await http.get(
            "/permissions", params={"source": "uploads"}, headers=headers
        )
    return _upload(response)


async def test_basic_lists_files(tmp_path: Path) -> None:
    (tmp_path / "files" / "a.txt").write_text("a")

    async with open_client(load("basic").build_app()) as http:
        response = await http.get("/", params={"action": "files"})

    names = [
        item["file"] for item in response.json()["data"]["sources"][0]["files"]
    ]
    assert "a.txt" in names


async def test_cookie_auth_roles() -> None:
    module = load("cookie_auth")

    assert not await _can_upload(module, {})
    assert await _can_upload(module, {"Cookie": "userRole=editor"})


async def test_cookie_auth_upload_needs_role(tmp_path: Path) -> None:
    app = load("cookie_auth").build_app()
    params = {"action": "fileUpload", "source": "uploads"}
    files = {"files[0]": ("a.txt", b"a")}

    async with open_client(app) as http:
        guest = await http.post("/", params=params, files=files)
        admin = await http.post(
            "/",
            params=params,
            files=files,
            headers={"Cookie": "userRole=admin"},
        )

    assert guest.status_code == 403
    assert admin.status_code == 200
    assert (tmp_path / "files" / "uploads" / "a.txt").exists()


async def test_jwt_auth_roles() -> None:
    module = load("jwt_auth")
    token = module.make_token("editor", "john")

    assert not await _can_upload(module, {})
    assert await _can_upload(module, {"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize(
    "header",
    [
        "Bearer not-a-token",
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "Bearer "
        + jwt.encode(
            {"role": "admin", "exp": int(time.time()) + 60}, "wrong" * 8
        ),
        "Bearer " + jwt.encode({"role": "admin"}, SECRET),
        "Bearer "
        + jwt.encode(
            {"role": ["admin"], "exp": int(time.time()) + 60}, SECRET
        ),
    ],
    ids=["garbage", "scheme", "empty", "forged", "no-exp", "role-type"],
)
async def test_jwt_auth_rejects_bad_tokens(header: str) -> None:
    async with open_client(load("jwt_auth").build_app()) as http:
        response = await http.get(
            "/permissions", headers={"Authorization": header}
        )

    assert response.status_code == 401
    assert response.json()["data"]["messages"] == ["Invalid or expired token"]


async def test_jwt_auth_rejects_expired_token() -> None:
    module = load("jwt_auth")
    token = module.make_token("admin", "john", lifetime=-60)

    async with open_client(module.build_app()) as http:
        response = await http.get(
            "/permissions", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401


async def test_session_auth_login_flow() -> None:
    app = load("session_auth").build_app()
    params = {"action": "permissions", "source": "uploads"}

    async with open_client(app) as http:
        before = await http.get("/", params=params)
        login = await http.get("/login/editor")
        whoami = await http.get("/whoami")
        during = await http.get("/", params=params)
        await http.get("/logout")
        after = await http.get("/", params=params)
        bad = await http.get("/login/root")

    assert login.json() == {"role": "editor"}
    assert whoami.json() == {"role": "editor"}
    assert (_upload(before), _upload(during), _upload(after)) == (
        False,
        True,
        False,
    )
    assert bad.status_code == 422


def test_custom_svg_icon() -> None:
    icon = load("custom_svg").colored_icon

    pdf = icon(StatEntry("docs/report.pdf", is_file=True), 50, 60)
    folder = icon(StatEntry("photos", is_file=False), 100, 100)
    unsafe = icon(StatEntry("<b>&.txt", is_file=True), 100, 100)
    long = icon(StatEntry("a-very-long-name.zip", is_file=True), 100, 100)

    assert 'width="50" height="60"' in pdf
    assert "#e74c3c" in pdf
    assert ">PDF<" in pdf
    assert ">DIR<" in folder
    assert "#2ecc71" in folder
    assert "&lt;b&gt;&amp;.txt" in unsafe
    assert "<b>" not in unsafe
    assert ">a-very-long-...<" in long


async def test_custom_svg_serves_thumbnails(tmp_path: Path) -> None:
    (tmp_path / "files" / "notes.txt").write_text("n")

    async with open_client(load("custom_svg").build_app()) as http:
        listing = await http.get("/files")
        (item,) = listing.json()["data"]["sources"][0]["files"]
        thumb = (tmp_path / "files" / item["thumb"]).read_text()

    assert "#95a5a6" in thumb
    assert ">TXT<" in thumb


async def test_multi_instance_isolation(tmp_path: Path) -> None:
    (tmp_path / "files" / "public" / "p.txt").write_text("p")
    (tmp_path / "files" / "private" / "s.txt").write_text("s")
    app = load("multi_instance").build_app()
    admin = {"X-Admin-Token": "change-me"}

    async with open_client(app) as http:
        public = await http.get("/public/files")
        upload = await http.post(
            "/public/fileUpload", files={"files[0]": ("x.txt", b"x")}
        )
        anonymous = await http.get("/admin/files")
        wrong = await http.get(
            "/admin/files", headers={"X-Admin-Token": "nope"}
        )
        private = await http.get("/admin/files", headers=admin)

    assert _names(public) == ["p.txt"]
    assert upload.status_code == 403
    assert anonymous.status_code == 403
    assert wrong.status_code == 403
    assert _names(private) == ["s.txt"]


async def test_s3_app_starts() -> None:
    async with open_client(load("s3").build_app()) as http:
        response = await http.get("/ping")

    assert response.status_code == 200


async def test_multi_tenant_sources(tmp_path: Path) -> None:
    (tmp_path / "files" / "tenants" / "acme" / "a.txt").write_text("a")
    (tmp_path / "files" / "shared" / "s.txt").write_text("s")

    async with open_client(load("multi_tenant").build_app()) as http:
        acme = await http.get("/files", headers={"X-Tenant": "acme"})
        shared = await http.get("/files")
        unknown = await http.get("/files", headers={"X-Tenant": "initech"})

    (acme_source,) = acme.json()["data"]["sources"]
    (shared_source,) = shared.json()["data"]["sources"]
    assert acme_source["title"] == "ACME files"
    assert [item["file"] for item in acme_source["files"]] == ["a.txt"]
    assert [item["file"] for item in shared_source["files"]] == ["s.txt"]
    assert unknown.status_code == 403
