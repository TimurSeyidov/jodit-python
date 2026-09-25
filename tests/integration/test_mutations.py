"""Changing actions, ported from the jodit-nodejs v1 tests."""

import os
from typing import TYPE_CHECKING

import pytest

from jcpy.config.loader import build_config
from jcpy.errors import HttpError
from jcpy.services.operations import make_folder
from jcpy.services.thumbs import ThumbCounter, make_thumb
from jcpy.sources import SourcePool
from jcpy.storage import StatEntry
from jcpy.storage.local import LocalStorageAdapter
from tests.conftest import BASEURL, service_context, source_config, write_file

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient, Response

    from jcpy.types import JsonObject, JsonValue
    from tests.conftest import ClientFactory


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "test"
    write_file(base, "file.txt", "content")
    write_file(base, "image.jpg", "jpeg")
    write_file(base, "subdir/inner.txt", "inner")
    write_file(base, "folder/a.txt", "a")
    write_file(base, "folder/nested/b.txt", "b")
    write_file(base, "folder/_thumbs/a.txt.svg", "<svg/>")
    (base / "empty").mkdir()
    (base / "target").mkdir()
    return base


def config(root: Path, **settings: JsonValue) -> JsonObject:
    return source_config(root, defaultFilesKey="files", **settings)


async def call(http: AsyncClient, action: str, **params: str) -> Response:
    return await http.get(
        "/", params={"action": action, "source": "test", **params}
    )


def messages(response: Response) -> list[str]:
    result: list[str] = response.json()["data"]["messages"]
    return result


def deny(action: str, **rule: JsonValue) -> JsonValue:
    return [{"role": "*", action: False, **rule}]


class TestFileUpload:
    async def test_multiple_files(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/",
                data={"action": "fileUpload", "source": "test"},
                files=[
                    ("files", ("pic.png", b"png", "image/png")),
                    ("files", ("data.csv", b"a,b", "text/csv")),
                ],
            )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "data": {
                "code": 220,
                "baseurl": BASEURL,
                "messages": [
                    "File pic.png was uploaded",
                    "File data.csv was uploaded",
                ],
                "files": ["pic.png", "data.csv"],
                "isImages": [True, False],
            },
        }
        assert (root / "data.csv").read_bytes() == b"a,b"

    async def test_array_field_names_and_subdirectory(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(source_config(root)) as http:
            response = await http.post(
                "/fileUpload",
                data={"source": "test", "path": "subdir"},
                files=[
                    ("files[0]", ("one.txt", b"1", "text/plain")),
                    ("files[1]", ("two.txt", b"2", "text/plain")),
                    ("other", ("skip.txt", b"x", "text/plain")),
                ],
            )

        assert response.json()["data"]["files"] == [
            "subdir/one.txt",
            "subdir/two.txt",
        ]
        assert (root / "subdir" / "two.txt").read_bytes() == b"2"
        assert not (root / "subdir" / "skip.txt").exists()

    async def test_unsafe_names_are_sanitized(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/fileUpload",
                files=[
                    ("files", ("../../evil:name?.txt", b"x", "text/plain"))
                ],
            )

        assert response.json()["data"]["files"] == [".._.._evil_name_.txt"]

    @pytest.mark.parametrize(
        ("strategy", "expected", "content"),
        [
            ("addNumber", "file-1.txt", "content"),
            ("replace", "file.txt", "new"),
        ],
    )
    async def test_same_name(
        self,
        connector_client: ClientFactory,
        root: Path,
        strategy: str,
        expected: str,
        content: str,
    ) -> None:
        write_file(root, "file-1.txt.keep", "")
        async with connector_client(
            config(root, saveSameFileNameStrategy=strategy)
        ) as http:
            response = await http.post(
                "/fileUpload",
                files=[("files", ("file.txt", b"new", "text/plain"))],
            )

        assert response.json()["data"]["files"] == [expected]
        assert (root / "file.txt").read_text() == content

    async def test_add_number_skips_taken_numbers(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        write_file(root, "file-1.txt", "taken")
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/fileUpload",
                files=[("files", ("file.txt", b"new", "text/plain"))],
            )

        assert response.json()["data"]["files"] == ["file-2.txt"]

    async def test_error_strategy(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(
            config(root, saveSameFileNameStrategy="error")
        ) as http:
            response = await http.post(
                "/fileUpload",
                files=[("files", ("file.txt", b"new", "text/plain"))],
            )

        assert response.status_code == 400
        assert messages(response) == ["File file.txt already exists"]

    async def test_forbidden_extension_rolls_back_the_request(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/fileUpload",
                files=[
                    ("files", ("ok.txt", b"ok", "text/plain")),
                    ("files", ("shell.php", b"<?php", "text/plain")),
                ],
            )

        assert response.status_code == 403
        assert messages(response) == ["File type is not in white list"]
        assert not (root / "ok.txt").exists()
        assert not (root / "shell.php").exists()

    async def test_size_limit(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(
            config(root, maxUploadFileSize="1kb")
        ) as http:
            response = await http.post(
                "/fileUpload",
                files=[("files", ("big.txt", b"x" * 1025, "text/plain"))],
            )

        assert response.status_code == 403
        assert messages(response) == ["File size exceeds the allowable"]
        assert not (root / "big.txt").exists()

    async def test_extension_rules(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules = deny("FILE_UPLOAD", extensions=["png"])
        async with connector_client(config(root, accessControl=rules)) as http:
            png = await http.post(
                "/fileUpload", files=[("files", ("a.png", b"p", "image/png"))]
            )
            txt = await http.post(
                "/fileUpload", files=[("files", ("a.txt", b"t", "text/plain"))]
            )

        assert png.status_code == 403
        assert txt.status_code == 200
        assert not (root / "a.png").exists()

    async def test_path_rules(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules = deny("FILE_UPLOAD", path=str(root / "subdir"))
        async with connector_client(config(root, accessControl=rules)) as http:
            allowed = await http.post(
                "/fileUpload",
                data={"path": "/"},
                files=[("files", ("a.txt", b"a", "text/plain"))],
            )
            denied = await http.post(
                "/fileUpload",
                data={"path": "/subdir"},
                files=[("files", ("a.txt", b"a", "text/plain"))],
            )

        assert allowed.status_code == 200
        assert denied.status_code == 403
        assert messages(denied) == ["Access denied"]

    @pytest.mark.parametrize(
        ("data", "status", "message"),
        [
            ({}, 400, "No files have been uploaded"),
            ({"source": "nope"}, 404, "Source not found"),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        data: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post(
                "/fileUpload",
                data=data,
                files=[("unrelated", ("a.txt", b"a", "text/plain"))],
            )

        assert response.status_code == status
        assert messages(response) == [message]

    async def test_validation(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await http.post("/fileUpload", json={"path": 1})

        assert messages(response) == [
            "Invalid input: expected string, received number"
        ]


class TestFileRemove:
    async def test_remove(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "fileRemove", name="file.txt")
            sub = await http.post(
                "/fileRemove",
                json={"source": "test", "path": "subdir", "name": "inner.txt"},
            )

        assert response.json() == {"success": True, "data": {"code": 220}}
        assert sub.status_code == 200
        assert not (root / "file.txt").exists()
        assert not (root / "subdir" / "inner.txt").exists()

    @pytest.mark.parametrize(
        ("params", "status", "message"),
        [
            ({"name": "missing.txt"}, 404, "File or directory not exists"),
            ({"name": "subdir"}, 400, "It is not a file!"),
            ({"name": "../../etc/passwd"}, 404, "Path does not exist"),
            (
                {"path": "subdir", "name": "../file.txt"},
                404,
                "Path does not exist",
            ),
            ({"name": "test.txt\0.jpg"}, 404, "Path does not exist"),
            ({"name": ""}, 400, "Name parameter is required"),
            ({"source": "nope", "name": "x"}, 404, "Source not found"),
            (
                {},
                400,
                "Invalid input: expected string, received undefined",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        params: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "fileRemove", **params)

        assert response.status_code == status
        assert messages(response) == [message]
        assert (root / "file.txt").exists()

    async def test_extension_rule(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules: JsonValue = [
            {"role": "guest", "FILE_REMOVE": True},
            {"role": "guest", "extensions": ["jpg"], "FILE_REMOVE": False},
        ]
        async with connector_client(config(root, accessControl=rules)) as http:
            txt = await call(http, "fileRemove", name="file.txt")
            jpg = await call(http, "fileRemove", name="image.jpg")

        assert txt.status_code == 200
        assert jpg.status_code == 403
        assert (root / "image.jpg").exists()


class TestFolderCreate:
    async def test_create(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "folderCreate", name="new folder")
            nested = await call(
                http, "folderCreate", path="subdir", name="child"
            )
            sanitized = await call(
                http, "folderCreate", name="folder:with*special?chars"
            )

        assert response.json()["data"] == {
            "code": 220,
            "messages": ["Directory successfully created"],
        }
        assert nested.status_code == 200
        assert sanitized.status_code == 200
        assert (root / "new folder").is_dir()
        assert (root / "subdir" / "child").is_dir()
        assert (root / "folder_with_special_chars").is_dir()

    @pytest.mark.parametrize(
        ("params", "status", "message"),
        [
            ({}, 400, "Name parameter is required"),
            ({"name": ""}, 400, "Name parameter is required"),
            ({"name": "subdir"}, 400, "Directory already exists"),
            ({"source": "nope", "name": "x"}, 404, "Source not found"),
            ({"path": "missing", "name": "x"}, 404, "Directory not found"),
            ({"path": "file.txt", "name": "x"}, 404, "Directory not found"),
            (
                {"path": "/../../etc", "name": "malicious"},
                404,
                "Directory not found",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        params: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "folderCreate", **params)

        assert response.status_code == status
        assert messages(response) == [message]

    @pytest.mark.parametrize("name", ["..", "con"])
    async def test_reserved_names_are_replaced(
        self, connector_client: ClientFactory, root: Path, name: str
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "folderCreate", name=name)

        assert response.status_code == 200
        assert (root / "_").is_dir()

    async def test_empty_sanitized_name(self, root: Path) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]

        with pytest.raises(HttpError, match="Folder name is required"):
            await make_folder(service_context(), source, "", "/")

    async def test_parent_outside_root(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        (root.parent / "outside").mkdir()
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderCreate", path="../outside", name="x"
            )

        assert response.status_code == 404
        assert messages(response) == ["Directory not found"]
        assert not (root.parent / "outside" / "x").exists()

    async def test_parent_check_mirrors_root_stripping(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        # The parent is checked by stripping the root from the joined
        # path, so an outside path must also pass get_path to succeed.
        (root.parent / "outside").mkdir()
        write_file(root, str(root.parent / "outside").lstrip("/") + "/k")
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderCreate", path="../outside", name="x"
            )

        assert response.status_code == 404
        assert messages(response) == ["Path does not exist"]

    async def test_permission_uses_new_folder_path(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules = deny("FOLDER_CREATE", path=str(root / "locked"))
        async with connector_client(config(root, accessControl=rules)) as http:
            denied = await call(http, "folderCreate", name="locked")
            allowed = await call(http, "folderCreate", name="open")

        assert denied.status_code == 403
        assert allowed.status_code == 200


class TestFolderRemove:
    @pytest.mark.parametrize("name", ["empty", "folder"])
    async def test_remove(
        self, connector_client: ClientFactory, root: Path, name: str
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "folderRemove", name=name)

        assert response.json()["data"] == {"code": 220}
        assert not (root / name).exists()

    async def test_remove_nested(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderRemove", path="folder", name="nested"
            )

        assert response.status_code == 200
        assert not (root / "folder" / "nested").exists()
        assert (root / "folder" / "a.txt").exists()

    @pytest.mark.parametrize(
        ("params", "status", "message"),
        [
            ({"name": "missing"}, 404, "Directory not exists"),
            ({"name": "file.txt"}, 400, "It is not a directory!"),
            ({"name": "../../etc"}, 404, "Path does not exist"),
            ({"name": "."}, 404, "Path does not exist"),
            ({"path": "folder", "name": ".."}, 404, "Path does not exist"),
            ({"name": ""}, 400, "Name parameter is required"),
            ({"source": "nope", "name": "x"}, 404, "Source not found"),
            (
                {},
                400,
                "name: Invalid input: expected string, received undefined",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        params: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "folderRemove", **params)

        assert response.status_code == status
        assert messages(response) == [message]
        assert root.is_dir()

    async def test_permission_is_checked_first(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(
            config(root, accessControl=deny("FOLDER_REMOVE", path=str(root)))
        ) as http:
            response = await call(http, "folderRemove", name="missing")

        assert response.status_code == 403


class TestMove:
    @pytest.mark.parametrize("action", ["fileMove", "folderMove"])
    async def test_move_file_and_folder(
        self, connector_client: ClientFactory, root: Path, action: str
    ) -> None:
        async with connector_client(config(root)) as http:
            file_response = await call(
                http, action, **{"from": "/file.txt", "path": "/target"}
            )
            folder_response = await call(
                http, action, **{"from": "folder", "path": "target"}
            )

        assert file_response.json()["data"] == {"code": 220}
        assert folder_response.status_code == 200
        assert (root / "target" / "file.txt").read_text() == "content"
        assert (root / "target" / "folder" / "nested" / "b.txt").exists()
        assert not (root / "folder").exists()

    @pytest.mark.parametrize("extra", [{}, {"path": ""}])
    async def test_move_to_root_without_path(
        self,
        connector_client: ClientFactory,
        root: Path,
        extra: dict[str, str],
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "fileMove", **{"from": "subdir/inner.txt", **extra}
            )

        assert response.status_code == 200
        assert (root / "inner.txt").exists()

    @pytest.mark.parametrize(
        ("params", "status", "message"),
        [
            ({"from": "missing.txt"}, 404, "Folder or directory not exists"),
            (
                {"from": "file.txt", "path": "missing"},
                404,
                "Destination directory not found",
            ),
            (
                {"from": "file.txt", "path": "image.jpg"},
                404,
                "Destination directory not found",
            ),
            ({"from": "/../../etc/passwd"}, 404, "Path does not exist"),
            ({"from": ""}, 400, "From parameter is required"),
            ({"source": "nope", "from": "x"}, 404, "Source not found"),
            (
                {},
                400,
                "Invalid input: expected string, received undefined",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        params: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "fileMove", **params)

        assert response.status_code == status
        assert messages(response) == [message]

    async def test_destination_outside_root(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        (root.parent / "test-evil").mkdir()
        (root / "test-evil").mkdir()
        async with connector_client(config(root)) as http:
            response = await call(
                http,
                "fileMove",
                **{"from": "file.txt", "path": "../test-evil"},
            )

        assert response.status_code == 404
        assert (root / "file.txt").exists()

    @pytest.mark.parametrize(
        ("source", "message"),
        [
            ("subdir/inner.txt", "File with same name already exists"),
            ("empty", "Folder with same name already exists"),
        ],
    )
    async def test_name_taken(
        self,
        connector_client: ClientFactory,
        root: Path,
        source: str,
        message: str,
    ) -> None:
        write_file(root, "target/inner.txt", "other")
        (root / "target" / "empty").mkdir()
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderMove", **{"from": source, "path": "target"}
            )

        assert response.status_code == 400
        assert messages(response) == [f"{message} in destination"]

    async def test_move_into_itself_fails(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http,
                "folderMove",
                **{"from": "folder", "path": "folder/nested"},
            )

        assert response.status_code == 400
        assert messages(response)[0].startswith("Unable to move: ")

    async def test_permissions_follow_the_item_kind(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(
            config(root, accessControl=deny("FOLDER_MOVE"))
        ) as http:
            folder = await call(
                http, "fileMove", **{"from": "empty", "path": "target"}
            )
            file = await call(
                http, "fileMove", **{"from": "file.txt", "path": "target"}
            )

        assert folder.status_code == 403
        assert file.status_code == 200

    async def test_source_permission(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules = deny("FILE_MOVE", path=str(root / "subdir"))
        async with connector_client(config(root, accessControl=rules)) as http:
            response = await call(
                http,
                "fileMove",
                **{"from": "subdir/inner.txt", "path": "target"},
            )

        assert response.status_code == 403


class TestCopy:
    async def test_copy_file_keeps_original(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "fileCopy", **{"from": "file.txt", "path": "target"}
            )

        assert response.json()["data"] == {"code": 220}
        assert (root / "file.txt").exists()
        assert (root / "target" / "file.txt").read_text() == "content"

    async def test_copy_into_same_folder_adds_suffix(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            for _ in range(2):
                await call(http, "fileCopy", **{"from": "file.txt"})
            await call(http, "folderCopy", **{"from": "empty"})

        assert (root / "file (1).txt").exists()
        assert (root / "file (2).txt").exists()
        assert (root / "empty (1)").is_dir()

    async def test_copy_folder_recursively(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderCopy", **{"from": "folder", "path": "target"}
            )

        assert response.status_code == 200
        copied = root / "target" / "folder"
        assert (copied / "a.txt").read_text() == "a"
        assert (copied / "nested" / "b.txt").read_text() == "b"
        assert (copied / "_thumbs" / "a.txt.svg").exists()
        assert (root / "folder" / "a.txt").exists()

    @pytest.mark.parametrize("path", ["folder", "folder/nested"])
    async def test_copy_folder_into_itself(
        self, connector_client: ClientFactory, root: Path, path: str
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderCopy", **{"from": "folder", "path": path}
            )

        assert response.status_code == 400
        assert messages(response) == ["Unable to copy folder into itself"]

    async def test_missing_source(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            file_missing = await call(http, "fileCopy", **{"from": "nope.txt"})
            folder_missing = await call(http, "folderCopy", **{"from": "nope"})
            no_from = await call(http, "fileCopy", **{"from": ""})

        assert file_missing.status_code == 404
        assert folder_missing.status_code == 404
        assert messages(no_from) == ["From parameter is required"]

    async def test_copy_failure(
        self,
        connector_client: ClientFactory,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def broken_copy(*_: object) -> None:
            msg = "disk full"
            raise OSError(msg)

        monkeypatch.setattr(LocalStorageAdapter, "copy_file", broken_copy)
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderCopy", **{"from": "folder", "path": "target"}
            )

        assert response.status_code == 400
        assert messages(response)[0].startswith("Unable to copy: ")

    async def test_copy_permissions(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(
            config(root, accessControl=deny("FILE_COPY"))
        ) as http:
            file = await call(http, "fileCopy", **{"from": "file.txt"})
            folder = await call(http, "folderCopy", **{"from": "empty"})

        assert file.status_code == 403
        assert folder.status_code == 200


class TestRename:
    async def test_rename_file_and_folder(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            file = await call(
                http, "fileRename", name="file.txt", newname="renamed.txt"
            )
            folder = await call(
                http, "folderRename", name="folder", newname="moved"
            )
            nested = await call(
                http,
                "fileRename",
                path="subdir",
                name="inner.txt",
                newname="x.txt",
            )

        assert file.json()["data"] == {"code": 220}
        assert folder.status_code == 200
        assert nested.status_code == 200
        assert (root / "renamed.txt").read_text() == "content"
        assert (root / "moved" / "nested" / "b.txt").exists()
        assert (root / "subdir" / "x.txt").exists()

    @pytest.mark.parametrize(
        ("new_name", "stored"),
        [
            ("renamed", "renamed.jpg"),
            ("malicious.php", "malicious.php.jpg"),
            ("upper.JPG", "upper.JPG"),
        ],
    )
    async def test_file_keeps_extension(
        self,
        connector_client: ClientFactory,
        root: Path,
        new_name: str,
        stored: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "fileRename", name="image.jpg", newname=new_name
            )

        assert response.status_code == 200
        assert (root / stored).exists()

    @pytest.mark.parametrize(
        ("action", "params", "status", "message"),
        [
            (
                "fileRename",
                {"name": "nope", "newname": "x"},
                404,
                "Path not exists",
            ),
            (
                "folderRename",
                {"name": "nope", "newname": "x"},
                404,
                "Folder or directory not exists",
            ),
            (
                "fileRename",
                {"name": "file.txt", "newname": "subdir/inner"},
                400,
                "New inner.txt already exists",
            ),
            (
                "fileRename",
                {"name": "image.jpg", "newname": "image.jpg"},
                400,
                "New image.jpg already exists",
            ),
            (
                "folderRename",
                {"name": "folder", "newname": "empty"},
                400,
                "Folder with new name already exists",
            ),
            (
                "fileRename",
                {"path": "subdir", "name": "../file.txt", "newname": "x"},
                404,
                "Path does not exist",
            ),
            (
                "fileRename",
                {"path": "subdir", "name": "inner.txt", "newname": "../x"},
                404,
                "Path does not exist",
            ),
            (
                "folderRename",
                {"name": "../..", "newname": "x"},
                404,
                "Path does not exist",
            ),
            (
                "fileRename",
                {"name": "", "newname": "x"},
                400,
                "Name parameter is required",
            ),
            (
                "fileRename",
                {"name": "file.txt", "newname": ""},
                400,
                "Newname parameter is required",
            ),
            (
                "fileRename",
                {"source": "nope", "name": "a", "newname": "b"},
                404,
                "Source not found",
            ),
        ],
    )
    async def test_errors(
        self,
        connector_client: ClientFactory,
        root: Path,
        action: str,
        params: dict[str, str],
        status: int,
        message: str,
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, action, **params)

        assert response.status_code == status
        assert messages(response) == [message]
        assert (root / "file.txt").exists()

    async def test_validation_styles(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            file = await call(http, "fileRename", name="file.txt")
            folder = await call(http, "folderRename", name="folder")

        assert messages(file) == [
            "Invalid input: expected string, received undefined"
        ]
        assert messages(folder) == [
            "newname: Invalid input: expected string, received undefined"
        ]

    async def test_rename_failure(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "folderRename", name="folder", newname="folder/nested/x"
            )

        assert response.status_code == 400
        assert messages(response)[0].startswith("Unable to rename: ")

    async def test_both_names_need_permission(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules = deny("FILE_RENAME", path=str(root / "locked"))
        async with connector_client(config(root, accessControl=rules)) as http:
            response = await call(
                http, "fileRename", name="file.txt", newname="locked.txt"
            )

        assert response.status_code == 403
        assert (root / "file.txt").exists()


class TestTraversal:
    async def test_folder_name_cannot_escape(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(http, "folderCreate", name="../evil-folder")

        assert response.status_code == 200
        assert (root / ".._evil-folder").is_dir()
        assert not (root.parent / "evil-folder").exists()

    async def test_acl_cannot_be_bypassed_with_dot_dot(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        rules: JsonValue = [
            {"role": "guest", "path": "/subdir", "FILE_REMOVE": True},
            {"role": "guest", "FILE_REMOVE": False},
        ]
        write_file(root, "root-protected.txt", "protected")
        async with connector_client(
            config(root, accessControl=rules, defaultRole="guest")
        ) as http:
            response = await call(
                http,
                "fileRemove",
                path="/subdir",
                name="../root-protected.txt",
            )

        assert response.status_code >= 400
        assert (root / "root-protected.txt").exists()


class TestEdgeCases:
    async def test_no_sources(self, connector_client: ClientFactory) -> None:
        async with connector_client({"sources": {}}) as http:
            response = await http.get("/fileRemove", params={"name": "x"})

        assert response.status_code == 404
        assert messages(response) == ["Source not found"]

    async def test_item_below_a_file(
        self, connector_client: ClientFactory, root: Path
    ) -> None:
        async with connector_client(config(root)) as http:
            response = await call(
                http, "fileMove", **{"from": "file.txt/x", "path": "target"}
            )

        assert response.status_code == 404
        assert messages(response) == ["Folder or directory not exists"]

    async def test_failing_existence_check_counts_as_missing(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]
        created: list[str] = []
        exists = source.storage.directory_exists

        async def broken(path: str) -> bool:
            if path != "new":
                return await exists(path)
            msg = "storage offline"
            raise OSError(msg)

        async def record(path: str) -> None:
            created.append(path)

        monkeypatch.setattr(source.storage, "directory_exists", broken)
        monkeypatch.setattr(source.storage, "create_directory", record)
        context = service_context()

        await make_folder(context, source, "new", "/")

        assert created == ["new"]

    async def test_failing_parent_check_counts_as_missing(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]

        async def broken(path: str) -> bool:
            msg = "storage offline"
            raise OSError(msg)

        monkeypatch.setattr(source.storage, "directory_exists", broken)

        with pytest.raises(HttpError, match="Directory not found"):
            await make_folder(service_context(), source, "new", "/")

    async def test_failing_thumb_folder_check_creates_it(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = SourcePool(build_config(config(root)))._build()["test"]

        async def broken(path: str) -> bool:
            msg = "storage offline"
            raise OSError(msg)

        monkeypatch.setattr(source.storage, "directory_exists", broken)

        thumb = await make_thumb(
            source, StatEntry("file.txt", is_file=True), ThumbCounter()
        )

        assert thumb.endswith("_thumbs/file.txt.svg")
        assert (root / "_thumbs").is_dir()


async def test_storage_errors_do_not_reveal_the_root(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)

    async with connector_client(source_config(tmp_path)) as http:
        response = await http.get(
            "/folderMove", params={"from": "a", "path": "a/b"}
        )

    assert response.status_code == 400
    (message,) = response.json()["data"]["messages"]
    assert message.startswith("Unable to move: Unable to move file.")
    assert "'a' -> 'a/b/a'" in message
    assert str(tmp_path) not in message
    assert os.path.realpath(tmp_path) not in message
