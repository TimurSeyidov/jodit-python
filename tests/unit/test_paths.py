"""Path handling against reference Node.js outputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from jcpy.config.models import AppConfig, SourceConfig
from jcpy.errors import HttpError
from jcpy.sources import Source, is_path_within_root
from jcpy.storage import (
    CorruptedPathError,
    FileStorage,
    PathTraversalError,
    StorageError,
    normalize_storage_path,
)
from jcpy.storage.local import LocalStorageAdapter
from tests.memory_storage import MemoryStorageAdapter

FIXTURES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "path_cases.json").read_text()
)
ERRORS: dict[str, type[StorageError]] = {
    "CorruptedPathError": CorruptedPathError,
    "PathTraversalError": PathTraversalError,
}


def remote_source(root: str) -> Source:
    settings = SourceConfig.model_validate(
        {
            "name": "remote",
            "title": "Remote",
            "baseurl": "http://files/",
            "root": root,
            "storageAdapter": "memory",
        }
    )
    return Source(
        "remote", settings, AppConfig(), FileStorage(MemoryStorageAdapter())
    )


@pytest.mark.parametrize(
    "case",
    FIXTURES["getPath"],
    ids=[f"{c['root']}|{c['rel']}" for c in FIXTURES["getPath"]],
)
async def test_get_path_matches_node(case: dict[str, Any]) -> None:
    source = remote_source(case["root"])
    root = source.get_root()
    expected = case["result"]

    if is_path_within_root(expected, root):
        assert await source.get_path(case["rel"]) == expected
    else:
        with pytest.raises(HttpError, match="Path does not exist"):
            await source.get_path(case["rel"])


@pytest.mark.parametrize(
    "case",
    FIXTURES["storage"],
    ids=[repr(c["path"]) for c in FIXTURES["storage"]],
)
def test_storage_normalizer_matches_flystorage(case: dict[str, Any]) -> None:
    if "error" in case:
        with pytest.raises(ERRORS[case["error"]]):
            normalize_storage_path(case["path"])
    else:
        assert normalize_storage_path(case["path"]) == case["result"]


@pytest.mark.parametrize(
    ("pathname", "root", "inside"),
    [
        ("/var/uploads", "/var/uploads", True),
        ("/var/uploads/a", "/var/uploads", True),
        ("/var/uploads-evil", "/var/uploads", False),
        ("/var/uploads-evil/a", "/var/uploads/", False),
        ("/anything", "/", True),
    ],
)
def test_is_path_within_root(pathname: str, root: str, inside: bool) -> None:
    assert is_path_within_root(pathname, root) is inside


def local_source(root: Path) -> Source:
    settings = SourceConfig.model_validate(
        {
            "name": "test",
            "title": "Test",
            "baseurl": "http://files/",
            "root": str(root),
        }
    )
    return Source(
        "test", settings, AppConfig(), FileStorage(LocalStorageAdapter(root))
    )


class TestLocalConfinement:
    async def test_symlinked_directory_outside_root(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "root"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        (root / "link").symlink_to(outside)
        source = local_source(root)

        for relative in ("link", "link/secret.txt", "link/new-file"):
            with pytest.raises(HttpError, match="Path does not exist"):
                await source.get_path(relative)

    async def test_symlink_inside_root_is_allowed(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "root"
        (root / "real").mkdir(parents=True)
        (root / "alias").symlink_to(root / "real")
        source = local_source(root)

        assert await source.get_path("alias") == f"{root}/alias"

    async def test_symlinked_root(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / "root").symlink_to(real)
        source = local_source(tmp_path / "root")

        assert await source.get_path("a/b") == f"{tmp_path}/root/a/b"

    async def test_missing_path_is_allowed(self, tmp_path: Path) -> None:
        source = local_source(tmp_path)

        assert await source.get_path("new/dir") == f"{tmp_path}/new/dir"

    async def test_null_byte(self, tmp_path: Path) -> None:
        source = local_source(tmp_path)

        with pytest.raises(HttpError, match="Path does not exist"):
            await source.get_path("a\0b")

    async def test_default_is_root(self, tmp_path: Path) -> None:
        source = local_source(tmp_path)

        assert await source.get_path() == str(tmp_path)
        assert source.relative(str(tmp_path)) == ""
        assert source.relative(f"{tmp_path}/a/b") == "a/b"


def test_relative_root_is_resolved_against_cwd() -> None:
    source = remote_source("files/test")

    assert source.get_root() == f"{Path.cwd()}/files/test"


def test_remote_source_without_root_uses_virtual_root() -> None:
    settings = SourceConfig.model_validate(
        {
            "name": "r",
            "title": "R",
            "baseurl": "http://files/",
            "storageAdapter": "memory",
        }
    )
    source = Source(
        "r", settings, AppConfig(), FileStorage(MemoryStorageAdapter())
    )

    assert source.is_virtual_root is True
    assert source.get_root() == "/"


def test_local_source_without_root_is_not_implemented() -> None:
    settings = SourceConfig.model_construct(
        name="l", title="L", baseurl="http://files/"
    )
    source = Source(
        "l", settings, AppConfig(), FileStorage(MemoryStorageAdapter())
    )

    with pytest.raises(HttpError) as info:
        source.get_root()

    assert info.value.status_code == 501
