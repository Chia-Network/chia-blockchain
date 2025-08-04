# Package: utils

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Generic, Optional, Protocol, TextIO, TypeVar, Union

import anyio
from typing_extensions import Self, final


class DBWrapperError(Exception):
    pass


class InternalError(DBWrapperError):
    pass


class PurposefulAbort(DBWrapperError):
    obj: object

    def __init__(self, obj: object) -> None:
        self.obj = obj


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


# TODO: are these ok missing type parameters so they stay generic?  or...
TConnection = TypeVar("TConnection", bound=ConnectionProtocol)  # type: ignore[type-arg]
TConnection_co = TypeVar("TConnection_co", bound=ConnectionProtocol, covariant=True)  # type: ignore[type-arg]
TUntransactionedConnection = TypeVar("TUntransactionedConnection")


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
class Transactioner(Generic[TConnection, TUntransactionedConnection]):
    create_connection: CreateConnectionCallable[TConnection]
    create_untransactioned_connection: Callable[[TConnection], TUntransactionedConnection]
    _write_connection: TConnection
    db_version: int = 1
    _log_file: Optional[TextIO] = None
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
    async def writer_outside_transaction(self) -> AsyncIterator[TUntransactionedConnection]:
        """
        Provides a connection without any active transaction.  These connection
        objects are generally made to be very limited.  An Sqlite specific example
        usage is to execute pragmas related to controlling foreign key enforcement
        which must be executed outside of a transaction.  If this task is already
        in a transaction, an error is raised immediately.
        """
        task = asyncio.current_task()
        assert task is not None
        if self._current_writer == task:
            if self._write_connection.in_transaction:
                raise Exception("can't nest for no transaction inside an active transaction")

            yield self.create_untransactioned_connection(self._write_connection)
            return

        async with self._lock:
            self._current_writer = task
            try:
                yield self.create_untransactioned_connection(self._write_connection)
            finally:
                self._current_writer = None

    @contextlib.asynccontextmanager
    async def writer(self) -> AsyncIterator[TConnection]:
        """
        Initiates a new, possibly nested, transaction. If this task is already
        in a transaction, none of the changes made as part of this transaction
        will become visible to others until that top level transaction commits.
        If this transaction fails (by exiting the context manager with an
        exception) this transaction will be rolled back, but the next outer
        transaction is not necessarily cancelled. It would also need to exit
        with an exception to be cancelled.
        """
        task = asyncio.current_task()
        assert task is not None
        if self._current_writer == task:
            # we allow nesting writers within the same task
            async with self._write_connection.savepoint_ctx(name=self._next_savepoint()):
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
