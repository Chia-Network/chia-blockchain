from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from typing import Any, AsyncIterator, Dict, Iterable, Optional

import aiosqlite

if aiosqlite.sqlite_version_info < (3, 32, 0):
    SQLITE_MAX_VARIABLE_NUMBER = 900
else:
    SQLITE_MAX_VARIABLE_NUMBER = 32700


class DBWrapper:
    """
    This object handles HeaderBlocks and Blocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection
    lock: asyncio.Lock

    def __init__(self, connection: aiosqlite.Connection):
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


async def execute_fetchone(
    c: aiosqlite.Connection, sql: str, parameters: Iterable[Any] = None
) -> Optional[sqlite3.Row]:
    rows = await c.execute_fetchall(sql, parameters)
    for row in rows:
        return row
    return None


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
        assert c != self._write_connection
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
    async def _savepoint_ctx(self) -> AsyncIterator[None]:
        name = self._next_savepoint()
        await self._write_connection.execute(f"SAVEPOINT {name}")
        try:
            yield
        except:  # noqa E722
            await self._write_connection.execute(f"ROLLBACK TO {name}")
            raise
        finally:
            # rollback to a savepoint doesn't cancel the transaction, it
            # just rolls back the state. We need to cancel it regardless
            await self._write_connection.execute(f"RELEASE {name}")

    @contextlib.asynccontextmanager
    async def writer(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Initiates a new, possibly nested, transaction. If this task is already
        in a transaction, none of the changes made as part of this transaction
        will become visible to others until that top level transaction commits.
        If this transaction fails (by exiting the context manager with an
        exception) this transaction will be rolled back, but the next outer
        transaction is not necessarily cancelled. It would also need to exit
        with an exception to be cancelled.
        The sqlite features this relies on are SAVEPOINT, ROLLBACK TO and RELEASE.
        """
        task = asyncio.current_task()
        assert task is not None
        if self._current_writer == task:
            # we allow nesting writers within the same task
            async with self._savepoint_ctx():
                yield self._write_connection
            return

        async with self._lock:
            async with self._savepoint_ctx():
                self._current_writer = task
                try:
                    yield self._write_connection
                finally:
                    self._current_writer = None

    @contextlib.asynccontextmanager
    async def writer_maybe_transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Initiates a write to the database. If this task is already in a write
        transaction with the DB, this is a no-op. Any changes made to the
        database will be rolled up into the transaction we're already in. If the
        current task is not already in a transaction, one will be created and
        committed (or rolled back in the case of an exception).
        """
        task = asyncio.current_task()
        assert task is not None
        if self._current_writer == task:
            # just use the existing transaction
            yield self._write_connection
            return

        async with self._lock:
            async with self._savepoint_ctx():
                self._current_writer = task
                try:
                    yield self._write_connection
                finally:
                    self._current_writer = None

    @contextlib.asynccontextmanager
    async def reader_no_transaction(self) -> AsyncIterator[aiosqlite.Connection]:
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
            # we allow nesting reading while also having a writer connection
            # open, within the same task
            yield self._write_connection
            return

        if task in self._in_use:
            yield self._in_use[task]
        else:
            c = await self._read_connections.get()
            try:
                # record our connection in this dict to allow nested calls in
                # the same task to use the same connection
                self._in_use[task] = c
                yield c
            finally:
                del self._in_use[task]
                self._read_connections.put_nowait(c)
