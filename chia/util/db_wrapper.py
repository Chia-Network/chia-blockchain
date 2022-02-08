from __future__ import annotations

import asyncio
import contextlib
import contextvars
import dataclasses
import random
from typing import AsyncIterator, Awaitable, Callable, Iterator, Optional, TypeVar
import weakref

import aiosqlite


surrounding_task: contextvars.ContextVar[Optional[asyncio.Task]] = contextvars.ContextVar(
    "surrounding_task",
    default=None,
)


T = TypeVar("T")


@contextlib.contextmanager
def set_contextvar(contextvar: contextvars.ContextVar[T], value: T) -> Iterator[None]:
    token = contextvar.set(value)
    try:
        yield
    finally:
        contextvar.reset(token)


@dataclasses.dataclass
class NewDbWrapper:
    get_connection: Callable[[], aiosqlite.Connection]
    # TODO: think about whether we ant this to be wrapper-specific or even smarter...
    #       probably avoiding the global is better.
    connections: weakref.WeakKeyDictionary[asyncio.Task, aiosqlite.Connection] = dataclasses.field(
        default_factory=weakref.WeakKeyDictionary,
    )

    @contextlib.asynccontextmanager
    async def savepoint(self) -> AsyncIterator[aiosqlite.Connection]:
        current_task = asyncio.current_task()
        # TODO: real error
        assert current_task is not None
        nested = current_task == surrounding_task.get()

        if nested:
            async with self._manage_savepoint(connection=self.connections[current_task]):
                yield self.connections[current_task]
        else:
            async with self._manage_new_connection(task=current_task):
                with set_contextvar(contextvar=surrounding_task, value=current_task):
                    async with self._manage_savepoint(connection=self.connections[current_task]):
                        yield self.connections[current_task]

    @contextlib.asynccontextmanager
    async def _manage_new_connection(self, task: asyncio.Task) -> AsyncIterator[None]:
        # TODO: https://github.com/python/mypy/issues/10750
        connection = self.get_connection()  # type: ignore[misc, operator]
        print(f" ==== {connection=}")
        try:
            self.connections[task] = connection
            async with connection:
                yield
        finally:
            if task in self.connections:
                del self.connections[task]

    @contextlib.asynccontextmanager
    async def _manage_savepoint(self, connection: aiosqlite.Connection) -> AsyncIterator[None]:
        # TODO: can we make this deterministic?
        savepoint_name = "x" + random.getrandbits(128).to_bytes(length=16, byteorder="big").hex()

        await connection.execute(f"SAVEPOINT {savepoint_name}")
        try:
            yield
        except BaseException:
            await connection.execute(f"ROLLBACK TO {savepoint_name}")
            raise
        else:
            await connection.execute(f"RELEASE {savepoint_name}")


class DBWrapper:
    """
    This object handles HeaderBlocks and Blocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection
    lock: asyncio.Lock
    db_version: int

    def __init__(self, connection: aiosqlite.Connection, db_version: int = 1):
        self.db = connection
        self.lock = asyncio.Lock()
        self.db_version = db_version

    async def begin_transaction(self):
        cursor = await self.db.execute("BEGIN TRANSACTION")
        await cursor.close()

    async def rollback_transaction(self):
        # Also rolls back the coin store, since both stores must be updated at once
        if self.db.in_transaction:
            cursor = await self.db.execute("ROLLBACK")
            await cursor.close()

    async def commit_transaction(self):
        await self.db.commit()
