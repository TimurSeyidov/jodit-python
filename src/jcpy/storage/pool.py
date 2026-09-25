"""Pool of connections to a remote file server (FTP, SFTP)."""

import contextlib
import threading
import time
import uuid
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from anyio import CancelScope, CapacityLimiter, to_thread

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from jcpy.storage.threads import TransferThreads


def remote_path(directory: str, path: str) -> str:
    """Path on the server of a storage path.

    Args:
        directory: Directory acting as the source root; absolute, or
            relative to the login directory (``""`` is the login
            directory itself).
        path: Storage path.

    Returns:
        ``directory`` joined with ``path``; the directory itself (``.``
        or ``/`` when empty) for the root.
    """
    base = directory.rstrip("/")
    absolute = directory.startswith("/")
    if not path:
        return base or ("/" if absolute else ".")
    if absolute or (base and base != "."):
        return f"{base}/{path}"
    return path


def replace_by_swap(
    rename: Callable[[str, str], object],
    remove: Callable[[str], object],
    source: str,
    target: str,
) -> None:
    """Rename ``source`` over an existing ``target`` without losing it.

    For servers whose rename refuses an existing target: the target is
    moved aside, and put back when the rename still fails.

    Args:
        rename: Blocking rename.
        remove: Blocking file removal.
        source: Existing path.
        target: Existing file replaced by ``source``.

    Raises:
        Exception: The target could not be moved aside (it is untouched)
            or the rename failed (the target is restored).
    """
    backup = f"{target}.{uuid.uuid4().hex}.old"
    rename(target, backup)
    try:
        rename(source, target)
    except BaseException:
        rename(backup, target)
        raise
    with contextlib.suppress(Exception):
        remove(backup)


class Failure(Enum):
    """What an exception raised by an operation says about its connection."""

    KEEP = "keep"
    """The server refused the command; the connection is still usable."""
    BROKEN = "broken"
    """The connection is in an unknown state and must be closed."""
    LOST = "lost"
    """The connection dropped; a reused one may have been closed idle."""


@dataclass(slots=True)
class _Idle[C]:
    connection: C
    since: float = field(default_factory=time.monotonic)


def _close_all[C](
    idle: list[_Idle[C]], close: Callable[[C], None], lock: threading.Lock
) -> None:
    with lock:
        entries = list(idle)
        idle.clear()
    for entry in entries:
        with contextlib.suppress(Exception):
            close(entry.connection)


class ConnectionPool[C]:
    """Reuses a few connections among concurrent operations.

    At most ``size`` connections are open at once; an operation waits
    for a free one. Connections idle longer than ``idle_timeout`` are
    closed instead of reused, and an operation that finds its reused
    connection dropped is retried once on a new one. Idle connections
    are closed by ``close()`` or when the pool is garbage collected.

    Args:
        connect: Opens a connection (blocking).
        close: Closes a connection (blocking, must not raise).
        classify: Tells what an exception means for the connection it
            was raised with.
        size: Most connections open at once.
        idle_timeout: Seconds a connection may stay idle.
    """

    def __init__(
        self,
        connect: Callable[[], C],
        close: Callable[[C], None],
        classify: Callable[[BaseException, C], Failure],
        *,
        size: int,
        idle_timeout: float,
    ) -> None:
        self.size = size
        self.idle_timeout = idle_timeout
        self._connect = connect
        self._close = close
        self._classify = classify
        self._idle: list[_Idle[C]] = []
        self._lock = threading.Lock()
        self._slots: CapacityLimiter | None = None
        self._finalizer = weakref.finalize(
            self, _close_all, self._idle, close, self._lock
        )

    def _limiter(self) -> CapacityLimiter:
        if self._slots is None:
            # Created lazily: a limiter needs a running event loop.
            self._slots = CapacityLimiter(self.size)
        return self._slots

    def _checkout(self) -> tuple[C, bool]:
        """Take an idle connection or open one; tell whether reused."""
        stale: list[C] = []
        found: C | None = None
        deadline = time.monotonic() - self.idle_timeout
        with self._lock:
            while self._idle:
                entry = self._idle.pop()
                if entry.since >= deadline:
                    found = entry.connection
                    break
                stale.append(entry.connection)
        for connection in stale:
            self._discard(connection)
        if found is not None:
            return found, True
        return self._connect(), False

    def _checkin(self, connection: C) -> None:
        with self._lock:
            self._idle.append(_Idle(connection))

    def _discard(self, connection: C) -> None:
        with contextlib.suppress(Exception):
            self._close(connection)

    def _settle(self, connection: C, error: BaseException) -> Failure:
        kind = self._classify(error, connection)
        if kind is Failure.KEEP:
            self._checkin(connection)
        else:
            self._discard(connection)
        return kind

    def _call[T](self, func: Callable[[C], T]) -> T:
        connection, reused = self._checkout()
        try:
            result = func(connection)
        except BaseException as error:
            if self._settle(connection, error) is not Failure.LOST:
                raise
            if not reused:
                raise
        else:
            self._checkin(connection)
            return result
        # The reused connection had been dropped: retry on a new one.
        connection = self._connect()
        try:
            result = func(connection)
        except BaseException as error:
            self._settle(connection, error)
            raise
        self._checkin(connection)
        return result

    async def run[T](
        self,
        func: Callable[[C], T],
        *,
        threads: TransferThreads | None = None,
    ) -> T:
        """Run a blocking operation with a pooled connection.

        Args:
            func: Operation getting the connection; retried once on a
                new connection when a reused one turns out dropped, so
                it must be safe to repeat.
            threads: Transfer threads to run in; anyio's default pool
                otherwise.

        Returns:
            What ``func`` returned.
        """
        async with self._limiter():
            if threads is not None:
                return await threads.run(self._call, func)
            return await to_thread.run_sync(self._call, func)

    @asynccontextmanager
    async def hold(self, probe: Callable[[C], object]) -> AsyncIterator[C]:
        """Keep one connection for a series of calls (a streamed read).

        A reused connection is checked with ``probe`` first and replaced
        when that fails. The connection goes back to the pool when the
        block ends normally and is closed when it raises.

        Args:
            probe: Cheap blocking command proving the connection alive.

        Yields:
            The connection, to be used from worker threads.
        """
        # A streamed body may be finished by another task than the one
        # that started it: the slot is held for a token, not the task.
        limiter, token = self._limiter(), object()
        await limiter.acquire_on_behalf_of(token)
        try:
            connection = await to_thread.run_sync(self._fresh, probe)
            try:
                yield connection
            except BaseException:
                with CancelScope(shield=True):
                    await to_thread.run_sync(self._discard, connection)
                raise
            self._checkin(connection)
        finally:
            limiter.release_on_behalf_of(token)

    def _fresh(self, probe: Callable[[C], object]) -> C:
        connection, reused = self._checkout()
        if not reused:
            return connection
        try:
            probe(connection)
        except Exception:  # any failure: open a new one
            self._discard(connection)
            return self._connect()
        return connection

    def close(self) -> None:
        """Close the idle connections; the pool stays usable."""
        _close_all(self._idle, self._close, self._lock)
