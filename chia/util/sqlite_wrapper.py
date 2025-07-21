from __future__ import annotations

import contextlib
import functools
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Self, TextIO, Union, cast

import aiosqlite
import aiosqlite.context
import anyio
from aiosqlite import Cursor

from chia.util.transactioner import (
    ConnectionProtocol,
    CreateConnectionCallable,
    Transactioner,
    manage_connection,
    sql_trace_callback,
    # CursorProtocol, AwaitableEnterable,
)

# if TYPE_CHECKING:
#     _protocol_check: AwaitableEnterable[Cursor] = cast(aiosqlite.Cursor, None)


@dataclass
class SqliteConnection:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[ConnectionProtocol[aiosqlite.context.Result[aiosqlite.Cursor]]] = cast(
            "SqliteConnection", None
        )

    _connection: aiosqlite.Connection

    async def close(self) -> None:
        return await self._connection.close()

    def execute(self, *args: Any, **kwargs: Any) -> aiosqlite.context.Result[Cursor]:
        return self._connection.execute(*args, **kwargs)

    @property
    def in_transaction(self) -> bool:
        return self._connection.in_transaction

    async def rollback(self) -> None:
        await self._connection.rollback()

    async def configure_as_reader(self) -> None:
        await self.execute("pragma query_only")

    async def read_transaction(self) -> None:
        await self.execute("BEGIN DEFERRED;")

    async def __aenter__(self) -> Self:
        await self._connection.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        return await self._connection.__aexit__(exc_type, exc_val, exc_tb)

    @contextlib.asynccontextmanager
    async def savepoint_ctx(self, name: str) -> AsyncIterator[None]:
        await self._connection.execute(f"SAVEPOINT {name}")
        try:
            yield
        except:
            await self._connection.execute(f"ROLLBACK TO {name}")
            raise
        finally:
            # rollback to a savepoint doesn't cancel the transaction, it
            # just rolls back the state. We need to cancel it regardless
            await self._connection.execute(f"RELEASE {name}")


async def sqlite_create_connection(
    database: Union[str, Path],
    uri: bool = False,
    log_file: Optional[TextIO] = None,
    name: Optional[str] = None,
    row_factory: Optional[type[aiosqlite.Row]] = None,
) -> SqliteConnection:
    # To avoid https://github.com/python/cpython/issues/118172
    connection = await aiosqlite.connect(database=database, uri=uri, cached_statements=0)

    if log_file is not None:
        await connection.set_trace_callback(functools.partial(sql_trace_callback, file=log_file, name=name))

    if row_factory is not None:
        connection.row_factory = row_factory

    return SqliteConnection(_connection=connection)


@contextlib.asynccontextmanager
async def managed(
    database: Union[str, Path],
    *,
    db_version: int = 1,
    uri: bool = False,
    reader_count: int = 4,
    log_path: Optional[Path] = None,
    journal_mode: str = "WAL",
    synchronous: Optional[str] = None,
    foreign_keys: Optional[bool] = None,
    row_factory: Optional[type[aiosqlite.Row]] = None,
) -> AsyncIterator[Transactioner[SqliteConnection]]:
    if foreign_keys is None:
        foreign_keys = False

    async with contextlib.AsyncExitStack() as async_exit_stack:
        if log_path is None:
            log_file = None
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = async_exit_stack.enter_context(log_path.open("a", encoding="utf-8"))

        write_connection = await async_exit_stack.enter_async_context(
            manage_connection(
                create_connection=sqlite_create_connection, database=database, uri=uri, log_file=log_file, name="writer"
            ),
        )
        await (await write_connection.execute(f"pragma journal_mode={journal_mode}")).close()
        if synchronous is not None:
            await (await write_connection.execute(f"pragma synchronous={synchronous}")).close()

        await (await write_connection.execute(f"pragma foreign_keys={'ON' if foreign_keys else 'OFF'}")).close()

        write_connection._connection.row_factory = row_factory

        self = Transactioner(
            create_connection=sqlite_create_connection,
            _write_connection=write_connection,
            db_version=db_version,
            _log_file=log_file,
        )

        for index in range(reader_count):
            read_connection = await async_exit_stack.enter_async_context(
                manage_connection(
                    create_connection=sqlite_create_connection,
                    database=database,
                    uri=uri,
                    log_file=log_file,
                    name=f"reader-{index}",
                ),
            )
            read_connection._connection.row_factory = row_factory

            await self.add_connection(c=read_connection)
        try:
            yield self
        finally:
            with anyio.CancelScope(shield=True):
                while self._num_read_connections > 0:
                    await self._read_connections.get()
                    self._num_read_connections -= 1


async def create(
    create_connection: CreateConnectionCallable[SqliteConnection],
    database: Union[str, Path],
    *,
    db_version: int = 1,
    uri: bool = False,
    reader_count: int = 4,
    log_path: Optional[Path] = None,
    journal_mode: str = "WAL",
    synchronous: Optional[str] = None,
    foreign_keys: bool = False,
) -> Transactioner[SqliteConnection]:
    # WARNING: please use .managed() instead
    if log_path is None:
        log_file = None
    else:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")
    write_connection = await create_connection(database=database, uri=uri, log_file=log_file, name="writer")
    await (await write_connection.execute(f"pragma journal_mode={journal_mode}")).close()
    if synchronous is not None:
        await (await write_connection.execute(f"pragma synchronous={synchronous}")).close()

    await (await write_connection.execute(f"pragma foreign_keys={'ON' if foreign_keys else 'OFF'}")).close()

    self = Transactioner(
        create_connection=create_connection,
        _write_connection=write_connection,
        db_version=db_version,
        _log_file=log_file,
    )

    for index in range(reader_count):
        read_connection = await create_connection(
            database=database,
            uri=uri,
            log_file=log_file,
            name=f"reader-{index}",
        )
        await self.add_connection(c=read_connection)

    return self
