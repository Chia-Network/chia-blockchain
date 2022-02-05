from __future__ import annotations

import asyncio
import contextlib
import contextvars
import weakref
from typing import AsyncIterator, Iterator, Optional, TypeVar

import aiosqlite


already_entered: contextvars.ContextVar[bool] = contextvars.ContextVar("already_entered", default=False)
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


connection_locks: weakref.WeakKeyDictionary[aiosqlite.Connection, asyncio.Lock] = weakref.WeakKeyDictionary()


class DBWrapper:
    """
    This object handles HeaderBlocks and Blocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection
    db_version: int

    def __init__(self, connection: aiosqlite.Connection, db_version: int = 1):
        connection_locks.setdefault(key=connection, default=asyncio.Lock())
        self.db = connection
        self.db_version = db_version

    # TODO: Deprecate this, I do not like properties as an API.
    @property
    def lock(self) -> aiosqlite.Connection:
        return connection_locks[self.db]

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

    @contextlib.asynccontextmanager
    async def locked_transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Lock against concurrent usage of the same db connection and enter, rollback,
        and commit transactions as needed.  The lock is tied to the specific db
        connection object.  Nested usage within a single asyncio task does nothing for
        the inner uses.  Uses of the same connection across different tasks will
        block each other via the lock.
        """
        current_task = asyncio.current_task()
        in_new_task = current_task != surrounding_task.get()

        if in_new_task:
            # initialize in new tasks to force new tasks to acquire resources
            already_entered.set(False)
            surrounding_task.set(current_task)
        elif already_entered.get():
            yield self.db
            return

        # TODO: add a lock acquisition timeout
        #       maybe https://docs.python.org/3/library/asyncio-task.html#asyncio.wait_for
        async with self.lock:
            with set_contextvar(contextvar=already_entered, value=True):
                await self.begin_transaction()
                try:
                    yield self.db
                except BaseException:
                    await self.rollback_transaction()
                    raise
                else:
                    await self.commit_transaction()
