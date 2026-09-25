"""Connection pool and helpers shared by the remote adapters."""

import gc

import anyio
import pytest

from jcpy.storage.pool import (
    ConnectionPool,
    Failure,
    remote_path,
    replace_by_swap,
)


@pytest.mark.parametrize(
    ("directory", "path", "expected"),
    [
        ("", "", "."),
        ("", "a/b", "a/b"),
        (".", "", "."),
        (".", "a", "a"),
        ("/", "", "/"),
        ("/", "a", "/a"),
        ("/srv/files/", "", "/srv/files"),
        ("/srv/files", "a", "/srv/files/a"),
        ("uploads/", "", "uploads"),
        ("uploads", "a", "uploads/a"),
    ],
)
def test_remote_path(directory: str, path: str, expected: str) -> None:
    assert remote_path(directory, path) == expected


class FakeServer:
    def __init__(self, files: dict[str, bytes], *, refuse: str = "") -> None:
        self.files = files
        self.refuse = refuse

    def rename(self, source: str, target: str) -> None:
        if target in self.files or self.refuse == target:
            raise OSError(f"cannot rename to {target}")
        self.files[target] = self.files.pop(source)

    def remove(self, path: str) -> None:
        del self.files[path]


class TestReplaceBySwap:
    def test_replaces(self) -> None:
        server = FakeServer({"new": b"n", "old": b"o"})

        replace_by_swap(server.rename, server.remove, "new", "old")

        assert server.files == {"old": b"n"}

    def test_failure_restores_the_target(self) -> None:
        server = FakeServer({"new": b"n", "old": b"o"})
        original = server.rename

        def rename(source: str, target: str) -> None:
            if source == "new":
                raise OSError("denied")
            original(source, target)

        with pytest.raises(OSError, match="denied"):
            replace_by_swap(rename, server.remove, "new", "old")

        assert server.files == {"new": b"n", "old": b"o"}

    def test_target_that_cannot_move_is_untouched(self) -> None:
        server = FakeServer({"new": b"n", "old": b"o"})

        def rename(source: str, target: str) -> None:
            if source == "old":
                raise OSError("locked")
            server.rename(source, target)

        with pytest.raises(OSError, match="locked"):
            replace_by_swap(rename, server.remove, "new", "old")

        assert server.files == {"new": b"n", "old": b"o"}

    def test_leftover_backup_is_ignored(self) -> None:
        server = FakeServer({"new": b"n", "old": b"o"})

        def remove(path: str) -> None:
            raise OSError("busy")

        replace_by_swap(server.rename, remove, "new", "old")

        assert server.files["old"] == b"n"
        assert len(server.files) == 2


class Connection:
    count = 0

    def __init__(self) -> None:
        Connection.count += 1
        self.number = Connection.count
        self.closed = False
        self.alive = True


def make_pool(
    classify: Failure = Failure.KEEP, **options: float
) -> tuple[ConnectionPool[Connection], list[Connection]]:
    opened: list[Connection] = []

    def connect() -> Connection:
        connection = Connection()
        opened.append(connection)
        return connection

    def close(connection: Connection) -> None:
        connection.closed = True

    pool = ConnectionPool(
        connect,
        close,
        lambda error, connection: classify,
        size=int(options.get("size", 2)),
        idle_timeout=options.get("idle_timeout", 60),
    )
    return pool, opened


class TestConnectionPool:
    async def test_reuses_connections(self) -> None:
        pool, opened = make_pool()

        first = await pool.run(lambda c: c.number)
        second = await pool.run(lambda c: c.number)

        assert first == second
        assert len(opened) == 1

    async def test_limits_open_connections(self) -> None:
        pool, opened = make_pool(size=2)

        async def slow() -> None:
            await pool.run(lambda c: anyio.from_thread.run(anyio.sleep, 0.05))

        async with anyio.create_task_group() as group:
            for _ in range(6):
                group.start_soon(slow)

        assert len(opened) == 2

    async def test_refused_command_keeps_the_connection(self) -> None:
        pool, opened = make_pool(Failure.KEEP)

        def refuse(connection: Connection) -> None:
            raise ValueError("refused")

        with pytest.raises(ValueError, match="refused"):
            await pool.run(refuse)
        await pool.run(lambda c: None)

        assert len(opened) == 1
        assert not opened[0].closed

    async def test_broken_connection_is_closed(self) -> None:
        pool, opened = make_pool(Failure.BROKEN)

        def fail(connection: Connection) -> None:
            raise ValueError("broken")

        with pytest.raises(ValueError, match="broken"):
            await pool.run(fail)

        assert opened[0].closed
        assert pool._idle == []

    async def test_lost_reused_connection_is_retried_once(self) -> None:
        pool, opened = make_pool(Failure.LOST)
        await pool.run(lambda c: None)
        opened[0].alive = False

        def use(connection: Connection) -> int:
            if not connection.alive:
                raise ConnectionResetError
            return connection.number

        assert await pool.run(use) == opened[1].number
        assert opened[0].closed

    async def test_lost_new_connection_is_not_retried(self) -> None:
        pool, opened = make_pool(Failure.LOST)

        def fail(connection: Connection) -> None:
            raise ConnectionResetError

        with pytest.raises(ConnectionResetError):
            await pool.run(fail)

        assert len(opened) == 1

    async def test_failing_retry_is_raised(self) -> None:
        pool, opened = make_pool(Failure.LOST)
        await pool.run(lambda c: None)

        def fail(connection: Connection) -> None:
            raise ConnectionResetError

        with pytest.raises(ConnectionResetError):
            await pool.run(fail)

        assert len(opened) == 2
        assert all(connection.closed for connection in opened)

    async def test_idle_connections_expire(self) -> None:
        pool, opened = make_pool(idle_timeout=60)
        await pool.run(lambda c: None)
        pool._idle[0].since -= 61

        await pool.run(lambda c: None)

        assert opened[0].closed
        assert len(opened) == 2

    async def test_hold_replaces_a_dead_connection(self) -> None:
        pool, opened = make_pool()
        await pool.run(lambda c: None)
        opened[0].alive = False

        def probe(connection: Connection) -> None:
            if not connection.alive:
                raise ConnectionResetError

        async with pool.hold(probe) as connection:
            assert connection is opened[1]

        assert opened[0].closed
        assert pool._idle[0].connection is opened[1]

    async def test_hold_closes_the_connection_on_errors(self) -> None:
        pool, opened = make_pool()

        with pytest.raises(RuntimeError):
            async with pool.hold(lambda c: None):
                raise RuntimeError

        assert opened[0].closed
        assert pool._idle == []

    async def test_close_and_garbage_collection(self) -> None:
        pool, opened = make_pool()
        await pool.run(lambda c: None)

        pool.close()

        assert opened[0].closed
        await pool.run(lambda c: None)
        del pool
        gc.collect()
        assert opened[1].closed
