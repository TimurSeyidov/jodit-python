"""Thread capacity reserved for moving file contents."""

from typing import TYPE_CHECKING

from anyio import CapacityLimiter, to_thread

if TYPE_CHECKING:
    from collections.abc import Callable

TRANSFER_THREADS = 16
"""Threads one adapter may use at once to move file contents."""


class TransferThreads:
    """Worker threads for transfers, separate from anyio's default pool.

    Long uploads and downloads then wait for each other instead of
    occupying the default pool that quick operations (stat, listing,
    deletes) run in.

    Args:
        total: Most transfer calls running at once.
    """

    def __init__(self, total: int = TRANSFER_THREADS) -> None:
        self.total = total
        self._limiter: CapacityLimiter | None = None

    async def run[T](self, func: Callable[..., T], *args: object) -> T:
        """Run a blocking transfer call in a worker thread.

        Args:
            func: Blocking callable.
            *args: Its positional arguments.

        Returns:
            What ``func`` returned.
        """
        if self._limiter is None:
            # Created lazily: a limiter needs a running event loop.
            self._limiter = CapacityLimiter(self.total)
        return await to_thread.run_sync(func, *args, limiter=self._limiter)
