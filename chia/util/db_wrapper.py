import asyncio
import contextlib

import aiosqlite


class DBWrapper:
    """
    This object handles HeaderBlocks and Blocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection
    lock: asyncio.Lock
    allow_upgrades: bool
    db_version: int

    def __init__(self, connection: aiosqlite.Connection, allow_upgrades: bool = False, db_version: int = 1):
        self.db = connection
        self.allow_upgrades = allow_upgrades
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

    # @contextlib.asynccontextmanager
    # async def defer_foreign_keys(self):
    #     # TODO: this cannot be nested
    #     cursor = await self.db.execute("PRAGMA defer_foreign_keys;")
    #     row = await cursor.fetchone()
    #     existing_value = row[0]
    #     # TODO: something other than an assert
    #     # We are interpolating this into SQL, let's make sure we know what it is.
    #     assert isinstance(existing_value, int)
    #     try:
    #         await self.db.execute("PRAGMA defer_foreign_keys = 1;")
    #         yield
    #     finally:
    #         await self.db.execute(f"PRAGMA defer_foreign_keys = {existing_value};")
