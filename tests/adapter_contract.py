"""Behaviour every storage adapter shares, as reusable tests.

Subclass ``AdapterContract`` in a ``Test*`` class that provides an
``adapter`` fixture: an empty storage with streaming support.
"""

from functools import partial
from io import BytesIO
from typing import TYPE_CHECKING

import anyio
import pytest

from jcpy.helpers.concurrency import gather_limited
from jcpy.storage.base import CHUNK_SIZE, FileWasNotFoundError

if TYPE_CHECKING:
    from jcpy.storage.base import StatEntry, StreamingStorageAdapter

BODY = bytes(range(256)) * (CHUNK_SIZE // 256 * 2 + 3)  # 3 chunks


async def listing(
    adapter: StreamingStorageAdapter, path: str = "", *, deep: bool = False
) -> dict[str, StatEntry]:
    return {entry.path: entry async for entry in adapter.list(path, deep=deep)}


async def chunks(adapter: StreamingStorageAdapter, path: str) -> list[bytes]:
    return [chunk async for chunk in adapter.iter_file(path)]


class FailingReader:
    """Binary source whose reads fail after the first chunk."""

    def __init__(self) -> None:
        self.position = 0

    def read(self, size: int = -1) -> bytes:
        if self.position:
            raise OSError("disk error")
        self.position += CHUNK_SIZE
        return BODY[:CHUNK_SIZE]

    def seek(self, position: int) -> int:
        self.position = position
        return position

    def tell(self) -> int:
        return self.position


class AdapterContract:
    async def test_write_and_read(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("a/b/c.txt", b"hello")

        assert await adapter.read("a/b/c.txt") == b"hello"
        assert await adapter.directory_exists("a/b")

    async def test_write_replaces(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("file.txt", b"first version")
        await adapter.write("file.txt", b"second")

        assert await adapter.read("file.txt") == b"second"
        assert set(await listing(adapter)) == {"file.txt"}

    async def test_read_missing(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        with pytest.raises(FileWasNotFoundError):
            await adapter.read("missing.txt")

    async def test_streaming_round_trip(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write_file("dir/big.bin", BytesIO(BODY))

        received = await chunks(adapter, "dir/big.bin")

        assert b"".join(received) == BODY
        assert all(0 < len(chunk) <= CHUNK_SIZE for chunk in received)

    async def test_write_file_from_the_current_position(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        source = BytesIO(b"skipped|kept")
        source.seek(8)

        await adapter.write_file("part.txt", source)

        assert await adapter.read("part.txt") == b"kept"

    async def test_streaming_a_missing_file(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        with pytest.raises(FileWasNotFoundError):
            await chunks(adapter, "missing.bin")

    async def test_stopping_a_stream_early(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("big.bin", BODY)

        stream = adapter.iter_file("big.bin")
        first = await anext(stream)
        await stream.aclose()  # type: ignore[attr-defined]

        assert first == BODY[: len(first)]
        assert await adapter.read("big.bin") == BODY

    async def test_stream_finished_by_another_task(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        # A download reads its first chunk in the request handler and the
        # rest in the response task.
        await adapter.write("big.bin", BODY)
        stream = adapter.iter_file("big.bin")
        received = [await anext(stream)]

        async def finish() -> None:
            received.extend([chunk async for chunk in stream])

        async with anyio.create_task_group() as group:
            group.start_soon(finish)

        assert b"".join(received) == BODY
        assert await adapter.read("big.bin") == BODY

    async def test_stat(self, adapter: StreamingStorageAdapter) -> None:
        await adapter.write("dir/file.txt", b"12345")

        file = await adapter.stat("dir/file.txt")
        folder = await adapter.stat("dir")
        root = await adapter.stat("")

        assert (file.path, file.is_file, file.size) == (
            "dir/file.txt",
            True,
            5,
        )
        assert file.last_modified_ms
        assert (folder.path, folder.is_directory) == ("dir", True)
        assert root.is_directory
        with pytest.raises(OSError, match=r"."):
            await adapter.stat("missing")

    async def test_list(self, adapter: StreamingStorageAdapter) -> None:
        await adapter.write("top.txt", b"123")
        await adapter.write("dir/inner.txt", b"1")
        await adapter.create_directory("dir/empty")

        shallow = await listing(adapter)
        deep = await listing(adapter, deep=True)
        inner = await listing(adapter, "dir")

        assert {path: entry.type for path, entry in shallow.items()} == {
            "top.txt": "file",
            "dir": "directory",
        }
        assert set(deep) == {"top.txt", "dir", "dir/inner.txt", "dir/empty"}
        assert set(inner) == {"dir/inner.txt", "dir/empty"}
        assert shallow["top.txt"].size in {3, None}

    async def test_existence(self, adapter: StreamingStorageAdapter) -> None:
        await adapter.write("dir/file.txt", b"x")

        assert await adapter.file_exists("dir/file.txt")
        assert not await adapter.file_exists("dir")
        assert not await adapter.file_exists("missing")
        assert await adapter.directory_exists("dir")
        assert await adapter.directory_exists("")
        assert not await adapter.directory_exists("dir/file.txt")
        assert not await adapter.directory_exists("missing")

    async def test_failed_write_keeps_the_previous_file(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("dir/a.bin", b"old")

        with pytest.raises(OSError, match="disk error"):
            await adapter.write_file("dir/a.bin", FailingReader())  # type: ignore[arg-type]

        assert await adapter.read("dir/a.bin") == b"old"
        assert set(await listing(adapter, "dir")) == {"dir/a.bin"}

    async def test_directory_over_a_file(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("file.txt", b"x")

        with pytest.raises(Exception, match=r"."):
            await adapter.create_directory("file.txt/sub")

        assert await adapter.read("file.txt") == b"x"

    async def test_delete_file_refuses_directories(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.create_directory("dir")

        with pytest.raises(Exception, match=r"."):
            await adapter.delete_file("dir")

        assert await adapter.directory_exists("dir")

    async def test_delete_directory_of_a_file(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("file.txt", b"x")

        await adapter.delete_directory("file.txt")

        assert not await adapter.file_exists("file.txt")

    async def test_create_directory(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.create_directory("x/y/z")
        await adapter.create_directory("x/y/z")

        assert await adapter.directory_exists("x/y/z")

    async def test_delete_file(self, adapter: StreamingStorageAdapter) -> None:
        await adapter.write("file.txt", b"x")

        await adapter.delete_file("file.txt")
        await adapter.delete_file("file.txt")

        assert not await adapter.file_exists("file.txt")

    async def test_delete_directory(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("dir/a.txt", b"a")
        await adapter.write("dir/sub/b.txt", b"b")
        await adapter.create_directory("dir/sub/empty")
        await adapter.write("kept.txt", b"k")

        await adapter.delete_directory("dir")
        await adapter.delete_directory("dir")

        assert set(await listing(adapter, deep=True)) == {"kept.txt"}

    async def test_copy_file(self, adapter: StreamingStorageAdapter) -> None:
        await adapter.write("a.bin", BODY)

        await adapter.copy_file("a.bin", "copies/b.bin")

        assert await adapter.read("copies/b.bin") == BODY
        assert await adapter.read("a.bin") == BODY

    async def test_move_file(self, adapter: StreamingStorageAdapter) -> None:
        await adapter.write("a.txt", b"a")

        await adapter.move_file("a.txt", "moved/b.txt")

        assert await adapter.read("moved/b.txt") == b"a"
        assert not await adapter.file_exists("a.txt")

    async def test_move_over_a_file(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("a.txt", b"new")
        await adapter.write("b.txt", b"old")

        await adapter.move_file("a.txt", "b.txt")

        assert await adapter.read("b.txt") == b"new"
        assert not await adapter.file_exists("a.txt")

    async def test_file_over_a_directory(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("a.txt", b"a")
        await adapter.write("dir/inner.txt", b"i")
        await adapter.create_directory("empty")

        for target in ("dir", "empty"):
            with pytest.raises(Exception, match=r"."):
                await adapter.move_file("a.txt", target)
            with pytest.raises(Exception, match=r"."):
                await adapter.write(target, b"x")

        assert await adapter.read("a.txt") == b"a"
        assert await adapter.read("dir/inner.txt") == b"i"
        assert await adapter.directory_exists("empty")
        assert set(await listing(adapter)) == {"a.txt", "dir", "empty"}

    async def test_failed_move_keeps_the_target(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("b.txt", b"keep me")

        with pytest.raises(Exception, match=r"."):
            await adapter.move_file("missing.txt", "b.txt")

        assert await adapter.read("b.txt") == b"keep me"

    async def test_move_directory(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("dir/sub/a.txt", b"a")

        await adapter.move_file("dir", "renamed")

        assert await adapter.read("renamed/sub/a.txt") == b"a"
        assert not await adapter.directory_exists("dir")

    async def test_concurrent_operations(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        names = [f"many/{index}.txt" for index in range(24)]

        await gather_limited(
            [partial(adapter.write, name, name.encode()) for name in names]
        )
        contents = await gather_limited(
            [partial(adapter.read, name) for name in names]
        )

        assert contents == [name.encode() for name in names]
        assert len(await listing(adapter, "many")) == len(names)

    async def test_names_with_spaces_and_unicode(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("文件夹 1/报告 2.txt", b"x")

        assert set(await listing(adapter, deep=True)) == {
            "文件夹 1",
            "文件夹 1/报告 2.txt",
        }
        assert await adapter.read("文件夹 1/报告 2.txt") == b"x"

    async def test_no_temporary_files_are_left(
        self, adapter: StreamingStorageAdapter
    ) -> None:
        await adapter.write("a.txt", b"a")
        await adapter.write_file("a.txt", BytesIO(b"b"))
        await adapter.copy_file("a.txt", "c.txt")

        assert set(await listing(adapter)) == {"a.txt", "c.txt"}
