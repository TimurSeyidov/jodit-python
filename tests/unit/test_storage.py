"""Local storage adapter, storage facade and adapter registry."""

import os
from typing import TYPE_CHECKING

import pytest

from jcpy.config.models import SourceConfig
from jcpy.errors import HttpError
from jcpy.storage import (
    FileStorage,
    FileWasNotFoundError,
    LocalStorageAdapter,
    StatEntry,
    StorageError,
    create_storage_adapter,
    get_registered_storage_adapters,
    is_local_storage_source,
    register_storage_adapter,
)
from jcpy.storage.local import UnsupportedEntryError
from tests.memory_storage import MemoryStorageAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "root"


@pytest.fixture
def storage(root: Path) -> FileStorage:
    return FileStorage(LocalStorageAdapter(root))


async def collect(storage: FileStorage, path: str, *, deep: bool) -> set[str]:
    return {
        f"{entry.type}:{entry.path}"
        async for entry in storage.list(path, deep=deep)
    }


class TestLocalAdapter:
    async def test_write_creates_root_and_parents(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("/a/b/c.txt", b"data")

        assert (root / "a" / "b" / "c.txt").read_bytes() == b"data"
        assert await storage.read("a/b/c.txt") == b"data"

    async def test_write_replaces(self, storage: FileStorage) -> None:
        await storage.write("f.txt", b"long content")
        await storage.write("f.txt", b"short")

        assert await storage.read("f.txt") == b"short"

    async def test_stat_file_and_directory(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("dir/f.txt", b"12345")
        mtime = (root / "dir" / "f.txt").stat().st_mtime_ns / 1_000_000

        file_stat = await storage.stat("dir/f.txt")
        dir_stat = await storage.stat("dir")

        assert file_stat == StatEntry("dir/f.txt", True, 5, mtime)
        assert file_stat.type == "file"
        assert dir_stat.is_directory
        assert dir_stat.type == "directory"
        assert dir_stat.size is None

    async def test_stat_follows_symlinks(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("real.txt", b"abc")
        (root / "link.txt").symlink_to(root / "real.txt")

        assert (await storage.stat("link.txt")).size == 3

    async def test_stat_missing(self, storage: FileStorage) -> None:
        with pytest.raises(
            StorageError, match=r"^Unable to get stat\. Reason"
        ):
            await storage.stat("missing")

    async def test_read_missing(self, storage: FileStorage) -> None:
        with pytest.raises(StorageError) as info:
            await storage.read("missing.txt")

        assert str(info.value) == (
            "Unable to read the file. Reason: "
            "File was not found at location: missing.txt"
        )
        assert isinstance(info.value.__cause__, FileWasNotFoundError)

    async def test_list_shallow_and_deep(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("a.txt", b"")
        await storage.write("sub/b.txt", b"")
        await storage.write("sub/deeper/c.txt", b"")

        assert await collect(storage, "", deep=False) == {
            "file:a.txt",
            "directory:sub",
        }
        assert await collect(storage, "sub", deep=True) == {
            "file:sub/b.txt",
            "directory:sub/deeper",
            "file:sub/deeper/c.txt",
        }
        entry = await anext(aiter(storage.list("sub", deep=False)))
        assert entry.size is None
        assert entry.last_modified_ms is None

    async def test_list_rejects_symlinks(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("a.txt", b"")
        (root / "link").symlink_to(root / "a.txt")

        with pytest.raises(StorageError, match="Unsupported file entry"):
            await collect(storage, "", deep=False)

    async def test_list_missing_directory(self, storage: FileStorage) -> None:
        with pytest.raises(StorageError, match="Unable to list directory"):
            await collect(storage, "missing", deep=False)

    async def test_exists_checks(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("dir/f.txt", b"")

        assert await storage.file_exists("dir/f.txt") is True
        assert await storage.file_exists("dir") is False
        assert await storage.file_exists("nope") is False
        assert await storage.directory_exists("dir") is True
        assert await storage.directory_exists("dir/f.txt") is False
        assert await storage.directory_exists("dir/f.txt/x") is False
        assert await storage.directory_exists("nope") is False
        with pytest.raises(StorageError, match="file existence"):
            await storage.file_exists("dir/f.txt/x")

    async def test_directory_exists_other_errors(
        self, storage: FileStorage, root: Path
    ) -> None:
        loop = root / "loop"
        root.mkdir()
        loop.symlink_to(loop)

        with pytest.raises(StorageError, match="directory existence"):
            await storage.directory_exists("loop")

    async def test_delete_file(self, storage: FileStorage, root: Path) -> None:
        await storage.write("f.txt", b"")

        await storage.delete_file("f.txt")
        await storage.delete_file("f.txt")

        assert not (root / "f.txt").exists()

    async def test_delete_file_refuses_directories(
        self, storage: FileStorage
    ) -> None:
        await storage.create_directory("dir")

        with pytest.raises(StorageError, match="Unable to delete file"):
            await storage.delete_file("dir")

    async def test_create_and_delete_directory(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.create_directory("a/b")
        await storage.create_directory("a/b")
        await storage.write("a/b/f.txt", b"")

        await storage.delete_directory("a")
        await storage.delete_directory("a")

        assert not (root / "a").exists()

    async def test_delete_directory_on_file_and_link(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("f.txt", b"")
        await storage.create_directory("real")
        (root / "link").symlink_to(root / "real")

        await storage.delete_directory("f.txt")
        await storage.delete_directory("link")

        assert not (root / "f.txt").exists()
        assert not (root / "link").exists()
        assert (root / "real").is_dir()

    async def test_copy_and_move(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("f.txt", b"data")

        await storage.copy_file("f.txt", "copies/g.txt")
        await storage.move_file("f.txt", "moved/h.txt")
        await storage.create_directory("dir/inner")
        await storage.move_file("dir", "renamed/dir")

        assert (root / "copies" / "g.txt").read_bytes() == b"data"
        assert (root / "moved" / "h.txt").read_bytes() == b"data"
        assert not (root / "f.txt").exists()
        assert (root / "renamed" / "dir" / "inner").is_dir()

    async def test_copy_missing(self, storage: FileStorage) -> None:
        with pytest.raises(StorageError, match="Unable to copy file"):
            await storage.copy_file("missing", "x")

    async def test_move_missing(self, storage: FileStorage) -> None:
        with pytest.raises(StorageError, match="Unable to move file"):
            await storage.move_file("missing", "x")

    async def test_write_failure(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.write("f.txt", b"")

        with pytest.raises(StorageError, match="Unable to write the file"):
            await storage.write("f.txt/child", b"")

    async def test_create_directory_failure(
        self, storage: FileStorage
    ) -> None:
        await storage.write("f.txt", b"")

        with pytest.raises(StorageError, match="Unable to create directory"):
            await storage.create_directory("f.txt/child")

    async def test_delete_directory_failure(
        self, storage: FileStorage, root: Path
    ) -> None:
        await storage.create_directory("locked/inner")
        (root / "locked").chmod(0o500)
        try:
            with pytest.raises(StorageError, match="delete directory"):
                await storage.delete_directory("locked/inner")
        finally:
            (root / "locked").chmod(0o700)

    async def test_stat_unsupported_entry(
        self, storage: FileStorage, root: Path
    ) -> None:
        root.mkdir()
        os.mkfifo(root / "pipe")

        with pytest.raises(StorageError, match="Unsupported file entry"):
            await storage.stat("pipe")
        assert isinstance(UnsupportedEntryError(), OSError)

    async def test_traversal_is_rejected_before_the_adapter(
        self, storage: FileStorage
    ) -> None:
        with pytest.raises(StorageError, match="Path traversal detected"):
            await storage.read("../outside")

        with pytest.raises(StorageError, match="Corrupted path"):
            await storage.write("a\0b", b"")


class TestRegistry:
    def settings(self, **extra: object) -> SourceConfig:
        return SourceConfig.model_validate(
            {"name": "s", "title": "S", "baseurl": "http://f/", **extra}
        )

    def test_local_is_built_in(self, tmp_path: Path) -> None:
        settings = self.settings(root=str(tmp_path))

        assert "local" in get_registered_storage_adapters()
        assert is_local_storage_source(settings)
        assert isinstance(
            create_storage_adapter(settings), LocalStorageAdapter
        )

    def test_local_without_root(self) -> None:
        settings = SourceConfig.model_construct(
            name="s", title="S", baseurl="http://f/"
        )

        with pytest.raises(HttpError, match='needs a "root" directory'):
            create_storage_adapter(settings)

    def test_unknown_adapter(self) -> None:
        settings = self.settings(storageAdapter="azure")

        with pytest.raises(HttpError) as info:
            create_storage_adapter(settings)

        assert info.value.status_code == 400
        assert info.value.message.startswith(
            'Unknown storage adapter "azure" for source "s". '
            "Registered adapters: local"
        )

    def test_custom_adapter(self) -> None:
        adapter = MemoryStorageAdapter()
        register_storage_adapter("memory-test", lambda _: adapter)
        settings = self.settings(storageAdapter="memory-test")

        assert not is_local_storage_source(settings)
        assert create_storage_adapter(settings) is adapter
        assert "memory-test" in get_registered_storage_adapters()


class _FailingAdapter(MemoryStorageAdapter):
    """Adapter whose reads fail with a message naming absolute paths."""

    def __init__(self, root: Path, message: str) -> None:
        super().__init__()
        self.root = root
        self.message = message

    async def read(self, path: str) -> bytes:
        raise OSError(self.message)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("denied: '{root}/a/b.txt'", "denied: 'a/b.txt'"),
        ("denied: '{real}/a/b.txt'", "denied: 'a/b.txt'"),
        ("cannot open '{root}'", "cannot open '.'"),
        ("no paths here", "no paths here"),
    ],
)
async def test_errors_hide_the_storage_root(
    tmp_path: Path, template: str, expected: str
) -> None:
    root = tmp_path / "files"
    root.mkdir()
    message = template.format(root=root, real=os.path.realpath(root))
    storage = FileStorage(_FailingAdapter(root, message))

    with pytest.raises(StorageError) as caught:
        await storage.read("a/b.txt")

    assert str(caught.value) == (
        f"Unable to read the file. Reason: {expected}"
    )


async def test_errors_of_adapters_without_root_are_kept() -> None:
    class Failing(MemoryStorageAdapter):
        async def read(self, path: str) -> bytes:
            msg = "/somewhere/else"
            raise OSError(msg)

    with pytest.raises(StorageError, match=r"Reason: /somewhere/else$"):
        await FileStorage(Failing()).read("x")
