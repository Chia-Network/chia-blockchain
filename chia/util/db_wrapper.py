from __future__ import annotations

import asyncio
import contextlib
import functools
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, Optional, TextIO, Type, Union

import aiosqlite
from typing_extensions import final

if aiosqlite.sqlite_version_info < (3, 32, 0):
    SQLITE_MAX_VARIABLE_NUMBER = 900
else:
    SQLITE_MAX_VARIABLE_NUMBER = 32700

# integers in sqlite are limited by int64
SQLITE_INT_MAX = 2**63 - 1


async def execute_fetchone(
    c: aiosqlite.Connection, sql: str, parameters: Iterable[Any] = None
) -> Optional[sqlite3.Row]:
    rows = await c.execute_fetchall(sql, parameters)
    for row in rows:
        return row
    return None


async def _create_connection(
    database: Union[str, Path],
    uri: bool = False,
    log_file: Optional[TextIO] = None,
    name: Optional[str] = None,
) -> aiosqlite.Connection:
    connection = await aiosqlite.connect(database=database, uri=uri)

    if log_file is not None:
        await connection.set_trace_callback(functools.partial(sql_trace_callback, file=log_file, name=name))

    return connection


@contextlib.asynccontextmanager
async def manage_connection(
    database: Union[str, Path],
    uri: bool = False,
    log_path: Optional[Path] = None,
    name: Optional[str] = None,
) -> AsyncIterator[aiosqlite.Connection]:
    async with contextlib.AsyncExitStack() as exit_stack:
        connection: aiosqlite.Connection
        if log_path is not None:
            file = exit_stack.enter_context(log_path.open("a", encoding="utf-8"))
            connection = await _create_connection(database=database, uri=uri, log_file=file, name=name)
        else:
            connection = await _create_connection(database=database, uri=uri, name=name)

        try:
            yield connection
        finally:
            await connection.close()


def sql_trace_callback(req: str, file: TextIO, name: Optional[str] = None) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S.%f")
    if name is not None:
        line = f"{timestamp} {name} {req}\n"
    else:
        line = f"{timestamp} {req}\n"
    file.write(line)


def get_host_parameter_limit() -> int:
    # NOTE: This does not account for dynamically adjusted limits since it makes a
    #       separate db and connection.  If aiosqlite adds support we should use it.
    if sys.version_info >= (3, 11):
        connection = sqlite3.connect(":memory:")

        # sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER exists in 3.11, pylint
        limit_number = sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER  # pylint: disable=E1101
        host_parameter_limit = connection.getlimit(limit_number)
    else:
        # guessing based on defaults, seems you can't query

        # https://www.sqlite.org/changes.html#version_3_32_0
        # Increase the default upper bound on the number of parameters from 999 to 32766.
        if sqlite3.sqlite_version_info >= (3, 32, 0):
            host_parameter_limit = 32766
        else:
            host_parameter_limit = 999
    return host_parameter_limit


@final
class DBWrapper2:
    db_version: int
    host_parameter_limit: int
    _lock: asyncio.Lock
    _read_connections: asyncio.Queue[aiosqlite.Connection]
    _write_connection: aiosqlite.Connection
    _num_read_connections: int
    _in_use: Dict[asyncio.Task, aiosqlite.Connection]
    _current_writer: Optional[asyncio.Task]
    _savepoint_name: int
    _log_file: Optional[TextIO]

    async def add_connection(self, c: aiosqlite.Connection) -> None:
        # this guarantees that reader connections can only be used for reading
        assert c != self._write_connection
        await c.execute("pragma query_only")
        self._read_connections.put_nowait(c)
        self._num_read_connections += 1

    def __init__(
        self,
        connection: aiosqlite.Connection,
        db_version: int = 1,
        log_file: Optional[TextIO] = None,
    ) -> None:
        self._read_connections = asyncio.Queue()
        self._write_connection = connection
        self._lock = asyncio.Lock()
        self.db_version = db_version
        self._num_read_connections = 0
        self._in_use = {}
        self._current_writer = None
        self._savepoint_name = 0
        self._log_file = log_file
        self.host_parameter_limit = get_host_parameter_limit()

    @classmethod
    async def create(
        cls,
        database: Union[str, Path],
        *,
        db_version: int = 1,
        uri: bool = False,
        reader_count: int = 4,
        log_path: Optional[Path] = None,
        journal_mode: str = "WAL",
        synchronous: Optional[str] = None,
        foreign_keys: bool = False,
        row_factory: Optional[Type[aiosqlite.Row]] = None,
    ) -> DBWrapper2:
        if log_path is None:
            log_file = None
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", encoding="utf-8")
        write_connection = await _create_connection(database=database, uri=uri, log_file=log_file, name="writer")
        await (await write_connection.execute(f"pragma journal_mode={journal_mode}")).close()
        if synchronous is not None:
            await (await write_connection.execute(f"pragma synchronous={synchronous}")).close()

        await (await write_connection.execute(f"pragma foreign_keys={'ON' if foreign_keys else 'OFF'}")).close()

        write_connection.row_factory = row_factory

        self = cls(connection=write_connection, db_version=db_version, log_file=log_file)

        for index in range(reader_count):
            read_connection = await _create_connection(
                database=database,
                uri=uri,
                log_file=log_file,
                name=f"reader-{index}",
            )
            read_connection.row_factory = row_factory
            await self.add_connection(c=read_connection)

        return self

    async def close(self) -> None:
        try:
            while self._num_read_connections > 0:
                await (await self._read_connections.get()).close()
                self._num_read_connections -= 1
            await self._write_connection.close()
        finally:
            if self._log_file is not None:
                self._log_file.close()

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
    async def reader(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self.reader_no_transaction() as connection:
            if connection.in_transaction:
                yield connection
            else:
                await connection.execute("BEGIN DEFERRED;")
                try:
                    yield connection
                finally:
                    # close the transaction with a rollback instead of commit just in
                    # case any modifications were submitted through this reader
                    await connection.rollback()

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
