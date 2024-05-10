from __future__ import annotations

import asyncio
import contextlib
import functools
import secrets
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, TextIO, Tuple, Type, Union

import aiosqlite
import anyio
from typing_extensions import final

if aiosqlite.sqlite_version_info < (3, 32, 0):
    SQLITE_MAX_VARIABLE_NUMBER = 900
else:
    SQLITE_MAX_VARIABLE_NUMBER = 32700

# integers in sqlite are limited by int64
SQLITE_INT_MAX = 2**63 - 1


class DBWrapperError(Exception):
    pass


class ForeignKeyError(DBWrapperError):
    def __init__(self, violations: Iterable[Union[aiosqlite.Row, Tuple[str, object, str, object]]]) -> None:
        self.violations: List[Dict[str, object]] = []

        for violation in violations:
            if isinstance(violation, tuple):
                violation_dict = dict(zip(["table", "rowid", "parent", "fkid"], violation))
            else:
                violation_dict = dict(violation)
            self.violations.append(violation_dict)

        super().__init__(f"Found {len(self.violations)} FK violations: {self.violations}")


class NestedForeignKeyDelayedRequestError(DBWrapperError):
    def __init__(self) -> None:
        super().__init__("Unable to enable delayed foreign key enforcement in a nested request.")


class InternalError(DBWrapperError):
    pass


def generate_in_memory_db_uri() -> str:
    # We need to use shared cache as our DB wrapper uses different types of connections
    return f"file:db_{secrets.token_hex(16)}?mode=memory&cache=shared"


async def execute_fetchone(
    c: aiosqlite.Connection, sql: str, parameters: Optional[Iterable[Any]] = None
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
    log_file: Optional[TextIO] = None,
    name: Optional[str] = None,
) -> AsyncIterator[aiosqlite.Connection]:
    connection: aiosqlite.Connection
    connection = await _create_connection(database=database, uri=uri, log_file=log_file, name=name)

    try:
        yield connection
    finally:
        with anyio.CancelScope(shield=True):
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
@dataclass
class DBWrapper2:
    _write_connection: aiosqlite.Connection
    db_version: int = 1
    _log_file: Optional[TextIO] = None
    host_parameter_limit: int = get_host_parameter_limit()
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _read_connections: asyncio.Queue[aiosqlite.Connection] = field(default_factory=asyncio.Queue)
    _num_read_connections: int = 0
    _in_use: Dict[asyncio.Task[object], aiosqlite.Connection] = field(default_factory=dict)
    _current_writer: Optional[asyncio.Task[object]] = None
    _savepoint_name: int = 0

    async def add_connection(self, c: aiosqlite.Connection) -> None:
        # this guarantees that reader connections can only be used for reading
        assert c != self._write_connection
        await c.execute("pragma query_only")
        self._read_connections.put_nowait(c)
        self._num_read_connections += 1

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls,
        database: Union[str, Path],
        *,
        db_version: int = 1,
        uri: bool = False,
        reader_count: int = 4,
        log_path: Optional[Path] = None,
        journal_mode: str = "WAL",
        synchronous: Optional[str] = None,
        foreign_keys: Optional[bool] = None,
        row_factory: Optional[Type[aiosqlite.Row]] = None,
    ) -> AsyncIterator[DBWrapper2]:
        if foreign_keys is None:
            foreign_keys = False

        async with contextlib.AsyncExitStack() as async_exit_stack:
            if log_path is None:
                log_file = None
            else:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = async_exit_stack.enter_context(log_path.open("a", encoding="utf-8"))

            write_connection = await async_exit_stack.enter_async_context(
                manage_connection(database=database, uri=uri, log_file=log_file, name="writer"),
            )
            await (await write_connection.execute(f"pragma journal_mode={journal_mode}")).close()
            if synchronous is not None:
                await (await write_connection.execute(f"pragma synchronous={synchronous}")).close()

            await (await write_connection.execute(f"pragma foreign_keys={'ON' if foreign_keys else 'OFF'}")).close()

            write_connection.row_factory = row_factory

            self = cls(_write_connection=write_connection, db_version=db_version, _log_file=log_file)

            for index in range(reader_count):
                read_connection = await async_exit_stack.enter_async_context(
                    manage_connection(
                        database=database,
                        uri=uri,
                        log_file=log_file,
                        name=f"reader-{index}",
                    ),
                )
                read_connection.row_factory = row_factory
                await self.add_connection(c=read_connection)

            try:
                yield self
            finally:
                with anyio.CancelScope(shield=True):
                    while self._num_read_connections > 0:
                        await self._read_connections.get()
                        self._num_read_connections -= 1

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
        # WARNING: please use .managed() instead
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

        self = cls(_write_connection=write_connection, db_version=db_version, _log_file=log_file)

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
    async def writer(
        self,
        foreign_key_enforcement_enabled: Optional[bool] = None,
    ) -> AsyncIterator[aiosqlite.Connection]:
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
            if foreign_key_enforcement_enabled is not None:
                # NOTE: Technically this is complaining even if the requested state is
                #       already in place.  This could be adjusted to allow nesting
                #       when the existing and requested states agree.  In this case,
                #       probably skip the nested foreign key check when exiting since
                #       we don't have many foreign key errors and so it is likely ok
                #       to save the extra time checking twice.
                raise NestedForeignKeyDelayedRequestError()
            async with self._savepoint_ctx():
                yield self._write_connection
            return

        async with self._lock:
            async with contextlib.AsyncExitStack() as exit_stack:
                if foreign_key_enforcement_enabled is not None:
                    await exit_stack.enter_async_context(
                        self._set_foreign_key_enforcement(enabled=foreign_key_enforcement_enabled),
                    )

                async with self._savepoint_ctx():
                    self._current_writer = task
                    try:
                        yield self._write_connection

                        if foreign_key_enforcement_enabled is not None and not foreign_key_enforcement_enabled:
                            await self._check_foreign_keys()
                    finally:
                        self._current_writer = None

    @contextlib.asynccontextmanager
    async def _set_foreign_key_enforcement(self, enabled: bool) -> AsyncIterator[None]:
        if self._current_writer is not None:
            raise InternalError("Unable to set foreign key enforcement state while a writer is held")

        async with self._write_connection.execute("PRAGMA foreign_keys") as cursor:
            result = await cursor.fetchone()
            if result is None:  # pragma: no cover
                raise InternalError("No results when querying for present foreign key enforcement state")
            [original_value] = result

        if original_value == enabled:
            yield
            return

        try:
            await self._write_connection.execute(f"PRAGMA foreign_keys={enabled}")
            yield
        finally:
            with anyio.CancelScope(shield=True):
                await self._write_connection.execute(f"PRAGMA foreign_keys={original_value}")

    async def _check_foreign_keys(self) -> None:
        async with self._write_connection.execute("PRAGMA foreign_key_check") as cursor:
            violations = list(await cursor.fetchall())

        if len(violations) > 0:
            raise ForeignKeyError(violations=violations)

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
