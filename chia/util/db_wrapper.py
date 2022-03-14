from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator, Dict, Iterator, Optional

import aiosqlite


class DBWrapper:
    """
    This object handles HeaderBlocks and Blocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection
    lock: asyncio.Lock

    def __init__(self, connection: aiosqlite.Connection, db_version: int = 1):
        self.db = connection
        self.lock = asyncio.Lock()

    async def begin_transaction(self):
        cursor = await self.db.execute("BEGIN TRANSACTION")
        await cursor.close()

    async def rollback_transaction(self):
        # Also rolls back the coin store, since both stores must be updated at once
        if self.db.in_transaction:
            cursor = await self.db.execute("ROLLBACK")
            await cursor.close()

    async def commit_transaction(self) -> None:
        await self.db.commit()


class DBWrapper2:
    db_version: int
    _lock: asyncio.Lock
    _read_connections: asyncio.Queue[aiosqlite.Connection]
    _write_connection: aiosqlite.Connection
    _num_read_connections: int
    _in_use: Dict[asyncio.Task, aiosqlite.Connection]
    _current_writer: Optional[asyncio.Task]
    _savepoint_name: int

    async def add_connection(self, c: aiosqlite.Connection) -> None:
        # this guarantees that reader connections can only be used for reading
        await c.execute("pragma query_only")
        self._read_connections.put_nowait(c)
        self._num_read_connections += 1

    def __init__(self, connection: aiosqlite.Connection, db_version: int = 1) -> None:
        self._read_connections = asyncio.Queue()
        self._write_connection = connection
        self._lock = asyncio.Lock()
        self.db_version = db_version
        self._num_read_connections = 0
        self._in_use = {}
        self._current_writer = None
        self._savepoint_name = 0

    async def close(self) -> None:
        while self._num_read_connections > 0:
            await (await self._read_connections.get()).close()
            self._num_read_connections -= 1
        await self._write_connection.close()

    def _next_savepoint(self) -> str:
        name = f"s{self._savepoint_name}"
        self._savepoint_name += 1
        return name

    @contextlib.asynccontextmanager
    async def _savepoint(self, connection) -> AsyncIterator[None]:
        name = self._next_savepoint()
        await connection.execute(f"SAVEPOINT {name}")
        try:
            # TODO: maybe yield out something to make it possible to cancel the
            #       savepoint other than raising an exception?
            yield
        except:  # noqa E722
            await connection.execute(f"ROLLBACK TO {name}")
            raise
        finally:
            # rollback to a savepoint doesn't cancel the transaction, it
            # just rolls back the state. We need to cancel it regardless
            await connection.execute(f"RELEASE {name}")

    @contextlib.contextmanager
    def _set_current_writer(self, writer: asyncio.Task) -> Iterator[None]:
        self._current_writer = writer
        try:
            yield
        finally:
            self._current_writer = None

    @contextlib.asynccontextmanager
    async def write_db(self) -> AsyncIterator[aiosqlite.Connection]:
        task = asyncio.current_task()
        assert task is not None

        if self._current_writer != task:
            # not nested inside an existing write context so acquire the lock
            async with self._lock:
                with self._set_current_writer(writer=task):
                    async with self._savepoint(connection=self._write_connection):
                        yield self._write_connection
        else:
            async with self._savepoint(connection=self._write_connection):
                yield self._write_connection

    @contextlib.asynccontextmanager
    async def _read_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await self._read_connections.get()
        try:
            yield connection
        finally:
            self._read_connections.put_nowait(connection)

    @contextlib.asynccontextmanager
    async def read_db(self) -> AsyncIterator[aiosqlite.Connection]:
        # there should have been read connections added
        assert self._num_read_connections > 0

        # we can have multiple concurrent readers, just pick a connection from
        # the pool of readers. If they're all busy, we'll wait for one to free
        # up.
        task = asyncio.current_task()
        assert task is not None

        # if this task currently holds the write lock, use the same connection,
        # so it can read back updates it has made to its transaction, even
        # though it hasn't been comitted yet
        if self._current_writer == task:
            # we allow nesting writers within the same task
            yield self._write_connection
            return

        maybe_connection = self._in_use.get(task)
        if maybe_connection is not None:
            yield maybe_connection
            return

        async with self._read_connection() as connection:
            # record our connection in this dict to allow nested calls in
            # the same task to use the same connection
            self._in_use[task] = connection
            try:
                yield connection
            finally:
                del self._in_use[task]
