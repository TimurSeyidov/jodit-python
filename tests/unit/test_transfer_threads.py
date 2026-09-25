"""Worker threads reserved for file transfers."""

import threading
from io import BytesIO
from typing import TYPE_CHECKING

import anyio

from jcpy.storage import LocalStorageAdapter
from jcpy.storage.threads import TRANSFER_THREADS, TransferThreads

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


async def test_runs_the_call_in_a_worker_thread() -> None:
    threads = TransferThreads()

    name = await threads.run(lambda: threading.current_thread().name)

    assert name != threading.main_thread().name
    assert threads.total == TRANSFER_THREADS


async def test_limits_concurrent_calls() -> None:
    threads = TransferThreads(total=2)
    lock = threading.Lock()
    running = peak = 0
    release = threading.Event()

    def work() -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        release.wait(5)
        with lock:
            running -= 1

    async with anyio.create_task_group() as group:
        for _ in range(5):
            group.start_soon(threads.run, work)
        await anyio.sleep(0.2)
        release.set()

    assert peak == 2


async def test_transfers_do_not_take_the_default_pool(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(tmp_path)
    default = anyio.to_thread.current_default_thread_limiter()
    before = default.borrowed_tokens
    seen: list[float] = []
    original = adapter._transfers.run

    async def spy(func: Callable[..., object], *args: object) -> object:
        def probe() -> object:
            seen.append(default.borrowed_tokens)
            return func(*args)

        return await original(probe)

    adapter._transfers.run = spy  # type: ignore[method-assign,assignment]

    await adapter.write_file("a.bin", BytesIO(b"data"))

    assert seen == [before]
    assert await adapter.read("a.bin") == b"data"
