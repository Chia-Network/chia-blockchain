from __future__ import annotations

import contextlib
import functools
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Optional, TextIO, TypeAlias, Union, cast

import aiosqlite
import aiosqlite.context
import anyio
from aiosqlite import Cursor
from typing_extensions import Self

from chia.util.transactioner import (
    ConnectionProtocol,
    CreateConnectionCallable,
    InternalError,
    Transactioner,
    manage_connection,
    sql_trace_callback,
)

SqliteTransactioner: TypeAlias = Transactioner["SqliteConnection", "UntransactionedSqliteConnection"]

# if TYPE_CHECKING:
#     _protocol_check: AwaitableEnterable[Cursor] = cast(aiosqlite.Cursor, None)


# TODO: think about the inheritance
# class NestedForeignKeyDelayedRequestError(DBWrapperError):
class NestedForeignKeyDelayedRequestError(Exception):
    def __init__(self) -> None:
        super().__init__("Unable to enable delayed foreign key enforcement in a nested request.")


# TODO: think about the inheritance
# class ForeignKeyError(DBWrapperError):
class ForeignKeyError(Exception):
    def __init__(self, violations: Iterable[Union[aiosqlite.Row, tuple[str, object, str, object]]]) -> None:
        self.violations: list[dict[str, object]] = []

        for violation in violations:
            if isinstance(violation, tuple):
                violation_dict = dict(zip(["table", "rowid", "parent", "fkid"], violation))
            else:
                violation_dict = dict(violation)
            self.violations.append(violation_dict)

        super().__init__(f"Found {len(self.violations)} FK violations: {self.violations}")


@dataclass
class UntransactionedSqliteConnection:
    _connection: SqliteConnection

    @contextlib.asynccontextmanager
    async def delay(self, *, foreign_key_enforcement_enabled: bool) -> AsyncIterator[None]:
        if self._connection.in_transaction and foreign_key_enforcement_enabled is not None:
            # NOTE: Technically this is complaining even if the requested state is
            #       already in place.  This could be adjusted to allow nesting
            #       when the existing and requested states agree.  In this case,
            #       probably skip the nested foreign key check when exiting since
            #       we don't have many foreign key errors and so it is likely ok
            #       to save the extra time checking twice.
            raise NestedForeignKeyDelayedRequestError

        async with self._connection._set_foreign_key_enforcement(enabled=foreign_key_enforcement_enabled):
            async with self._connection.savepoint_ctx("delay"):
                try:
                    yield
                finally:
                    await self._connection._check_foreign_keys()


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

    @contextlib.asynccontextmanager
    async def _set_foreign_key_enforcement(self, enabled: bool) -> AsyncIterator[None]:
        if self.in_transaction:
            raise InternalError("Unable to set foreign key enforcement state while a writer is held")

        async with self._connection.execute("PRAGMA foreign_keys") as cursor:
            result = await cursor.fetchone()
            if result is None:  # pragma: no cover
                raise InternalError("No results when querying for present foreign key enforcement state")
            [original_value] = result

        if original_value == enabled:
            yield
            return

        try:
            await self._connection.execute(f"PRAGMA foreign_keys={enabled}")
            yield
        finally:
            with anyio.CancelScope(shield=True):
                await self._connection.execute(f"PRAGMA foreign_keys={original_value}")

    async def _check_foreign_keys(self) -> None:
        async with self._connection.execute("PRAGMA foreign_key_check") as cursor:
            violations = list(await cursor.fetchall())

        if len(violations) > 0:
            raise ForeignKeyError(violations=violations)

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
) -> AsyncIterator[SqliteTransactioner]:
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
            create_untransactioned_connection=UntransactionedSqliteConnection,
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
) -> SqliteTransactioner:
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
        create_untransactioned_connection=UntransactionedSqliteConnection,
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
