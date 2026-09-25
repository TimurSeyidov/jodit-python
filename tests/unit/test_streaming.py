"""Streaming file contents through the storage layer."""

from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from starlette.datastructures import UploadFile

from jcpy.services.upload import _upload_size
from jcpy.storage import FileStorage, LocalStorageAdapter, StorageError
from jcpy.storage import local as local_module
from jcpy.storage.base import CHUNK_SIZE
from tests.memory_storage import MemoryStorageAdapter

if TYPE_CHECKING:
    from pathlib import Path

BODY = bytes(range(256)) * (CHUNK_SIZE // 256 * 3 + 7)  # 3+ chunks


async def collect(storage: FileStorage, path: str) -> list[bytes]:
    return [chunk async for chunk in storage.iter_file(path)]


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    return FileStorage(LocalStorageAdapter(tmp_path / "root"))


async def test_local_round_trip_in_chunks(storage: FileStorage) -> None:
    await storage.write_file("dir/big.bin", BytesIO(BODY))

    chunks = await collect(storage, "dir/big.bin")

    assert b"".join(chunks) == BODY
    assert len(chunks) == 4
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)


async def test_local_write_file_is_atomic(
    storage: FileStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await storage.write("a.bin", b"old")

    def broken_copy(path: Path, _source: object) -> None:
        path.write_bytes(b"n")
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(local_module, "_copy_new", broken_copy)
    with pytest.raises(StorageError, match="disk full"):
        await storage.write_file("a.bin", BytesIO(b"new"))

    assert (tmp_path / "root" / "a.bin").read_bytes() == b"old"
    assert sorted(p.name for p in (tmp_path / "root").iterdir()) == ["a.bin"]


async def test_missing_file_fails_on_first_chunk(
    storage: FileStorage,
) -> None:
    with pytest.raises(StorageError, match="File was not found"):
        await collect(storage, "missing.bin")


async def test_adapters_without_streaming_fall_back() -> None:
    adapter = MemoryStorageAdapter()
    storage = FileStorage(adapter)

    await storage.write_file("x.bin", BytesIO(BODY))
    chunks = await collect(storage, "x.bin")

    assert adapter.files["x.bin"] == BODY
    assert b"".join(chunks) == BODY
    assert len(chunks) == 4


async def test_upload_size_is_measured_when_unknown() -> None:
    upload = UploadFile(BytesIO(b"12345"), size=None)
    known = UploadFile(BytesIO(b"12345"), size=5)

    assert await _upload_size(upload) == 5
    assert upload.file.tell() == 0
    assert await _upload_size(known) == 5
