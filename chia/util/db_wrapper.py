import asyncio

import aiosqlite


class DBWrapper:
    """
    This object handles HeaderBlocks and Blocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection
    lock: asyncio.Lock

    def __init__(self, connection: aiosqlite.Connection):
        self.db = connection
        self.lock = asyncio.Lock()

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
