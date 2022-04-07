import asyncio
import contextlib

import aiosqlite


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
