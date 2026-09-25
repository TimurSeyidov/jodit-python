"""Bounded concurrency helper."""

import anyio
import pytest

from jcpy.helpers.concurrency import gather_limited


async def test_results_keep_the_order_of_jobs() -> None:
    async def job(value: int) -> int:
        await anyio.sleep((5 - value) / 1000)
        return value * 10

    jobs = [lambda value=value: job(value) for value in range(5)]

    assert await gather_limited(jobs) == [0, 10, 20, 30, 40]


async def test_at_most_limit_jobs_run_at_once() -> None:
    running = 0
    peak = 0

    async def job() -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await anyio.sleep(0.005)
        running -= 1

    await gather_limited([job] * 20, limit=3)

    assert peak == 3


async def test_first_error_is_raised_and_stops_new_jobs() -> None:
    started: list[int] = []

    async def job(value: int) -> int:
        started.append(value)
        if value == 1:
            msg = "boom"
            raise OSError(msg)
        await anyio.sleep(0.005)
        return value

    jobs = [lambda value=value: job(value) for value in range(10)]

    with pytest.raises(OSError, match="boom"):
        await gather_limited(jobs, limit=2)
    assert len(started) < 10


async def test_no_jobs() -> None:
    assert await gather_limited([]) == []
