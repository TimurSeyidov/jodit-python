"""Bounded concurrency for storage operations."""

from typing import TYPE_CHECKING, cast

import anyio

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

DEFAULT_LIMIT = 16
"""Operations run at once unless a caller asks otherwise."""


async def gather_limited[T](
    jobs: Sequence[Callable[[], Awaitable[T]]], limit: int = DEFAULT_LIMIT
) -> list[T]:
    """Run jobs concurrently, at most ``limit`` at a time.

    After a failure no new job starts; running ones finish.

    Args:
        jobs: Coroutine factories.
        limit: Most jobs running at once.

    Returns:
        Results in the order of ``jobs``.

    Raises:
        Exception: The first error a job raised, unchanged.
    """
    results: list[T | None] = [None] * len(jobs)
    errors: list[Exception] = []
    limiter = anyio.CapacityLimiter(limit)

    async def run(index: int, job: Callable[[], Awaitable[T]]) -> None:
        async with limiter:
            if errors:
                return
            try:
                results[index] = await job()
            except Exception as error:
                errors.append(error)

    async with anyio.create_task_group() as group:
        for index, job in enumerate(jobs):
            group.start_soon(run, index, job)
    if errors:
        raise errors[0]
    return cast("list[T]", results)
