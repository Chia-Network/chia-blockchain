from __future__ import annotations

import asyncio
import contextlib
import functools
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, AsyncIterator, Dict, Generator, Iterable, Optional, Type, Union

import aiosqlite
from typing_extensions import final

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

    @contextlib.asynccontextmanager
    async def locked_transaction(self, *, lock=True):
        # TODO: look into contextvars perhaps instead of this manual lock tracking
        if not lock:
            yield
            return

        # TODO: add a lock acquisition timeout
        #       maybe https://docs.python.org/3/library/asyncio-task.html#asyncio.wait_for

        async with self.lock:
            await self.begin_transaction()
            try:
                yield
            except BaseException:
                await self.rollback_transaction()
                raise
            else:
                await self.commit_transaction()


async def execute_fetchone(
    c: aiosqlite.Connection, sql: str, parameters: Iterable[Any] = None
) -> Optional[sqlite3.Row]:
    rows = await c.execute_fetchall(sql, parameters)
    for row in rows:
        return row
    return None


@dataclass
class create_connection:
    """Create an object that can both be `await`ed and `async with`ed to get a
    connection.
    """

    # def create_connection( (for searchability
    database: Union[str, Path]
    uri: bool = False
    log_path: Optional[Path] = None
    name: Optional[str] = None
    _connection: Optional[aiosqlite.Connection] = field(init=False, default=None)

    async def _create(self) -> aiosqlite.Connection:
        self._connection = await aiosqlite.connect(database=self.database, uri=self.uri)

        if self.log_path is not None:
            await self._connection.set_trace_callback(
                functools.partial(sql_trace_callback, path=self.log_path, name=self.name)
            )

        return self._connection

    def __await__(self) -> Generator[Any, None, Any]:
        return self._create().__await__()

    async def __aenter__(self) -> aiosqlite.Connection:
        self._connection = await self._create()
        return self._connection

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if self._connection is None:
            raise RuntimeError("exiting while self._connection is None")
        await self._connection.close()


def sql_trace_callback(req: str, path: Path, name: Optional[str] = None) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S.%f")
    with path.open(mode="a") as log:
        if name is not None:
            line = f"{timestamp} {name} {req}\n"
        else:
            line = f"{timestamp} {req}\n"
        log.write(line)


@final
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

    @classmethod
    async def create(
        cls,
        database: Union[str, Path],
        db_version: int = 1,
        uri: bool = False,
        reader_count: int = 4,
        log_path: Optional[Path] = None,
        journal_mode: str = "WAL",
        synchronous: Optional[str] = None,
    ) -> DBWrapper2:
        write_connection = await create_connection(database=database, uri=uri, log_path=log_path, name="writer")
        await (await write_connection.execute(f"pragma journal_mode={journal_mode}")).close()
        if synchronous is not None:
            await (await write_connection.execute(f"pragma synchronous={synchronous}")).close()

        self = cls(connection=write_connection, db_version=db_version)

        for index in range(reader_count):
            read_connection = await create_connection(
                database=database,
                uri=uri,
                log_path=log_path,
                name=f"reader-{index}",
            )
            await self.add_connection(c=read_connection)

        return self

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
        # though it hasn't been committed yet
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
