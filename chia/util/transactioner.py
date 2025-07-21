# Package: utils

from __future__ import annotations

import asyncio
import contextlib
import secrets
import sqlite3
import sys
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Generic, Optional, Protocol, TextIO, TypeVar, Union

import aiosqlite
import anyio
from typing_extensions import Self, final

if aiosqlite.sqlite_version_info < (3, 32, 0):
    SQLITE_MAX_VARIABLE_NUMBER = 900
else:
    SQLITE_MAX_VARIABLE_NUMBER = 32700

# integers in sqlite are limited by int64
SQLITE_INT_MAX = 2**63 - 1


class DBWrapperError(Exception):
    pass


class ForeignKeyError(DBWrapperError):
    def __init__(self, violations: Iterable[Union[aiosqlite.Row, tuple[str, object, str, object]]]) -> None:
        self.violations: list[dict[str, object]] = []

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


class PurposefulAbort(DBWrapperError):
    obj: object

    def __init__(self, obj: object) -> None:
        self.obj = obj


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

        limit_number = sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER
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


# class CursorProtocol(Protocol):
#     async def close(self) -> None: ...
#     # async def __aenter__(self) -> Self: ...
#     # async def __aexit__(
#     #     self,
#     #     exc_type: Optional[type[BaseException]],
#     #     exc_val: Optional[BaseException],
#     #     exc_tb: Optional[TracebackType],
#     # ) -> None: ...
#
#
# TCursor_co = TypeVar("TCursor_co", bound=CursorProtocol, covariant=True)
#
# class AwaitableEnterable(Protocol[TCursor_co]):
#     def __await__(self) -> TCursor_co: ...
#     async def __aenter__(self) -> TCursor_co: ...
#     async def __aexit__(
#         self,
#         exc_type: Optional[type[BaseException]],
#         exc_val: Optional[BaseException],
#         exc_tb: Optional[TracebackType],
#     ) -> None: ...


T_co = TypeVar("T_co", covariant=True)


class ConnectionProtocol(Protocol[T_co]):
    # TODO: this is presently matching aiosqlite.Connection, generalize

    async def close(self) -> None: ...
    def execute(self, *args: Any, **kwargs: Any) -> T_co: ...
    @property
    def in_transaction(self) -> bool: ...
    async def rollback(self) -> None: ...
    async def configure_as_reader(self) -> None: ...
    async def read_transaction(self) -> None: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None: ...

    @contextlib.asynccontextmanager
    async def savepoint_ctx(self, name: str) -> AsyncIterator[None]:
        yield


# a_cursor: CursorProtocol = cast(aiosqlite.Cursor, None)

# TODO: are these ok missing type parameters so they stay generic?  or...
TConnection = TypeVar("TConnection", bound=ConnectionProtocol)  # type: ignore[type-arg]
TConnection_co = TypeVar("TConnection_co", bound=ConnectionProtocol, covariant=True)  # type: ignore[type-arg]


class CreateConnectionCallable(Protocol[TConnection_co]):
    async def __call__(
        self,
        database: Union[str, Path],
        uri: bool = False,
        log_file: Optional[TextIO] = None,
        name: Optional[str] = None,
    ) -> TConnection_co: ...


@contextlib.asynccontextmanager
async def manage_connection(
    create_connection: CreateConnectionCallable[TConnection_co],
    database: Union[str, Path],
    uri: bool = False,
    log_file: Optional[TextIO] = None,
    name: Optional[str] = None,
) -> AsyncIterator[TConnection_co]:
    connection: TConnection_co
    connection = await create_connection(database=database, uri=uri, log_file=log_file, name=name)

    try:
        yield connection
    finally:
        with anyio.CancelScope(shield=True):
            await connection.close()


@final
@dataclass
class Transactioner(Generic[TConnection]):
    create_connection: CreateConnectionCallable[TConnection]
    _write_connection: TConnection
    db_version: int = 1
    _log_file: Optional[TextIO] = None
    host_parameter_limit: int = get_host_parameter_limit()
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _read_connections: asyncio.Queue[TConnection] = field(default_factory=asyncio.Queue)
    _num_read_connections: int = 0
    _in_use: dict[asyncio.Task[object], TConnection] = field(default_factory=dict)
    _current_writer: Optional[asyncio.Task[object]] = None
    _savepoint_name: int = 0

    async def add_connection(self, c: TConnection) -> None:
        # this guarantees that reader connections can only be used for reading
        assert c != self._write_connection
        await c.configure_as_reader()
        self._read_connections.put_nowait(c)
        self._num_read_connections += 1

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
    async def writer(
        self,
        foreign_key_enforcement_enabled: Optional[bool] = None,
    ) -> AsyncIterator[TConnection]:
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
                raise NestedForeignKeyDelayedRequestError
            async with self._write_connection.savepoint_ctx(name=self._next_savepoint()):
                yield self._write_connection
            return

        async with self._lock:
            async with contextlib.AsyncExitStack() as exit_stack:
                if foreign_key_enforcement_enabled is not None:
                    await exit_stack.enter_async_context(
                        self._set_foreign_key_enforcement(enabled=foreign_key_enforcement_enabled),
                    )

                async with self._write_connection.savepoint_ctx(name=self._next_savepoint()):
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
    async def writer_maybe_transaction(self) -> AsyncIterator[TConnection]:
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
            async with self._write_connection.savepoint_ctx(name=self._next_savepoint()):
                self._current_writer = task
                try:
                    yield self._write_connection
                finally:
                    self._current_writer = None

    @contextlib.asynccontextmanager
    async def reader(self) -> AsyncIterator[TConnection]:
        async with self.reader_no_transaction() as connection:
            if connection.in_transaction:
                yield connection
            else:
                await connection.read_transaction()
                try:
                    yield connection
                finally:
                    # close the transaction with a rollback instead of commit just in
                    # case any modifications were submitted through this reader
                    await connection.rollback()

    @contextlib.asynccontextmanager
    async def reader_no_transaction(self) -> AsyncIterator[TConnection]:
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
