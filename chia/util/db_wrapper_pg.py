from __future__ import annotations

import asyncio
import contextlib

# import functools
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Sequence, TextIO

import aiomysql

# import aiosqlite
import anyio
from typing_extensions import final

SQLITE_MAX_VARIABLE_NUMBER = 32700
SQLITE_INT_MAX = 2**63 - 1


def generate_in_memory_db_uri() -> str:
    # We need to use shared cache as our DB wrapper uses different types of connections
    return f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"


def generate_postgres_db_name() -> str:
    return f"db_{random.randint(0, 99999999)}"


async def execute_fetchone(
    c: aiomysql.Connection, sql: str, parameters: Optional[Sequence[Any]] = None
) -> Optional[Any]:
    async with c.cursor() as acur:
        await acur.execute(sql, parameters)
        return await acur.fetchone()


async def _create_connection(
    host: str,
    port: int,
    database: str,
    uri: bool = False,
    log_file: Optional[TextIO] = None,
    name: Optional[str] = None,
    row_factory: Optional[Any] = None,
) -> aiomysql.Connection:
    connection = await aiomysql.connect(
        host=host,
        port=port,
        user="root",
        password="mysql",
        db=database,
        loop=asyncio.get_event_loop(),
        cursorclass=aiomysql.DictCursor,
    )

    async with connection.cursor() as cursor:
        await cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
        await connection.commit()

    # if log_file is not None:
    #     await connection.set_trace_callback(functools.partial(sql_trace_callback, file=log_file, name=name))
    return connection


@contextlib.asynccontextmanager
async def manage_connection(
    host: str,
    port: int,
    database: str,
    uri: bool = False,
    log_file: Optional[TextIO] = None,
    name: Optional[str] = None,
    row_factory: Optional[Any] = None,
) -> AsyncIterator[aiomysql.Connection]:
    connection = await _create_connection(
        host=host, port=port, database=database, uri=uri, log_file=log_file, name=name
    )

    try:
        yield connection
    finally:
        with anyio.CancelScope(shield=True):
            connection.close()


def sql_trace_callback(req: str, file: TextIO, name: Optional[str] = None) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S.%f")
    if name is not None:
        line = f"{timestamp} {name} {req}\n"
    else:
        line = f"{timestamp} {req}\n"
    file.write(line)


def get_host_parameter_limit() -> int:
    return 32700


@final
@dataclass
class DBWrapperPG:
    _write_connection: aiomysql.Connection
    db_version: int = 1
    _log_file: Optional[TextIO] = None
    host_parameter_limit: int = get_host_parameter_limit()
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _read_connections: asyncio.Queue[aiomysql.Connection] = field(default_factory=asyncio.Queue)
    _num_read_connections: int = 0
    _in_use: Dict[asyncio.Task[object], aiomysql.Connection] = field(default_factory=dict)
    _current_writer: Optional[asyncio.Task[object]] = None
    _savepoint_name: int = 0

    async def add_connection(self, c: aiomysql.Connection) -> None:
        # this guarantees that reader connections can only be used for reading
        assert c != self._write_connection
        # await c.execute("pragma query_only")
        self._read_connections.put_nowait(c)
        self._num_read_connections += 1

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls,
        host: str,
        port: int,
        database: str,
        create_db: bool = True,
        *,
        db_version: int = 1,
        uri: bool = False,
        reader_count: int = 4,
        log_path: Optional[Path] = None,
        journal_mode: str = "WAL",
        synchronous: Optional[str] = None,
        foreign_keys: bool = False,
        row_factory: Optional[Any] = None,
    ) -> AsyncIterator[DBWrapperPG]:
        if create_db:
            async with aiomysql.connect(
                host=host, port=port, user="root", password="mysql", autocommit=True, cursorclass=aiomysql.DictCursor
            ) as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(f"CREATE DATABASE {database};")

        async with contextlib.AsyncExitStack() as async_exit_stack:
            if log_path is None:
                log_file = None
            else:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = async_exit_stack.enter_context(log_path.open("a", encoding="utf-8"))

            write_connection = await async_exit_stack.enter_async_context(
                manage_connection(host=host, port=port, database=database, uri=uri, log_file=log_file, name="writer"),
            )

            self = cls(_write_connection=write_connection, db_version=db_version, _log_file=log_file)

            for index in range(reader_count):
                read_connection = await async_exit_stack.enter_async_context(
                    manage_connection(
                        host=host,
                        port=port,
                        database=database,
                        uri=uri,
                        log_file=log_file,
                        name=f"reader-{index}",
                    ),
                )
                # read_connection.row_factory = row_factory
                # await read_connection.set_read_only(True)
                # await read_connection.set_isolation_level(psycopg.IsolationLevel.READ_COMMITTED)
                await self.add_connection(c=read_connection)

            try:
                yield self
            finally:
                with anyio.CancelScope(shield=True):
                    while self._num_read_connections > 0:
                        await self._read_connections.get()
                        self._num_read_connections -= 1
                if create_db:
                    async with aiomysql.connect(
                        host=host,
                        port=port,
                        user="root",
                        password="mysql",
                        autocommit=True,
                        cursorclass=aiomysql.DictCursor,
                    ) as connection:
                        async with connection.cursor() as cursor:
                            cursor.execute(f"DROP DATABASE {database};")

    @classmethod
    async def create(
        cls,
        host: str,
        port: int,
        database: str,
        *,
        db_version: int = 1,
        uri: bool = False,
        reader_count: int = 4,
        log_path: Optional[Path] = None,
        journal_mode: str = "WAL",
        synchronous: Optional[str] = None,
        foreign_keys: bool = False,
        row_factory: Optional[Any] = None,
    ) -> DBWrapperPG:
        # WARNING: please use .managed() instead
        if log_path is None:
            log_file = None
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", encoding="utf-8")
        write_connection = await _create_connection(
            host=host, port=port, database=database, uri=uri, log_file=log_file, name="writer"
        )
        await (await write_connection.execute(f"pragma journal_mode={journal_mode}")).close()
        if synchronous is not None:
            await (await write_connection.execute(f"pragma synchronous={synchronous}")).close()

        await (await write_connection.execute(f"pragma foreign_keys={'ON' if foreign_keys else 'OFF'}")).close()

        # write_connection.row_factory = row_factory

        self = cls(_write_connection=write_connection, db_version=db_version, _log_file=log_file)

        for index in range(reader_count):
            read_connection = await _create_connection(
                host=host,
                port=port,
                database=database,
                uri=uri,
                log_file=log_file,
                name=f"reader-{index}",
            )
            await self.add_connection(c=read_connection)

        return self

    async def close(self) -> None:
        # WARNING: please use .managed() instead
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
        cursor = await self._write_connection.cursor()
        await cursor.execute(f"SAVEPOINT {name}")
        try:
            yield
        except:  # noqa E722
            await cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")
            raise
        # finally:
        # rollback to a savepoint doesn't cancel the transaction, it
        # just rolls back the state. We need to cancel it regardless
        # await cursor.execute(f"RELEASE SAVEPOINT {name}")

    @contextlib.asynccontextmanager
    async def writer(self) -> AsyncIterator[aiomysql.Connection]:
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
            # await self._write_connection.commit()
            return

        async with self._lock:
            async with self._savepoint_ctx():
                self._current_writer = task
                try:
                    yield self._write_connection
                finally:
                    self._current_writer = None
            await self._write_connection.commit()

    @contextlib.asynccontextmanager
    async def writer_maybe_transaction(self) -> AsyncIterator[aiomysql.Connection]:
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
            # await self._write_connection.execute("START TRANSACTION READ WRITE")
            async with self._savepoint_ctx():
                self._current_writer = task
                try:
                    yield self._write_connection
                finally:
                    self._current_writer = None
            await self._write_connection.commit()

    @contextlib.asynccontextmanager
    async def reader(self) -> AsyncIterator[aiomysql.Connection]:
        async with self.reader_no_transaction() as connection:
            # yield connection
            # if connection.in_transaction:
            #     yield connection
            # else:
            # await connection.execute("START TRANSACTION READ ONLY")
            try:
                yield connection
            finally:
                pass
            # close the transaction with a rollback instead of commit just in
            # case any modifications were submitted through this reader
            # await connection.rollback()

    @contextlib.asynccontextmanager
    async def reader_no_transaction(self) -> AsyncIterator[aiomysql.Connection]:
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
