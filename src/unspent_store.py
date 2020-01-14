import asyncio
from typing import Dict, Optional

import aiosqlite

from src.consensus.constants import constants as consensus_constants
from src.types.full_block import FullBlock
from src.types.hashable import Hash, Unspent


class UnspentStore:
    db_name: str
    unspent_db: aiosqlite.Connection
    # Whether or not we are syncing
    sync_mode: bool = False
    lock: asyncio.Lock
    # TODO set the size limit of ram cache
    lce_unspent_coins: Dict

    @classmethod
    async def create(cls, db_name: str):
        self = cls()
        self.db_name = db_name

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.unspent_db = await aiosqlite.connect(self.db_name)
        await self.db.execute(
            (f"CREATE TABLE IF NOT EXISTS unspent("
             f"confirmed bigint,"
             f" spent bigint,"
             f" coin_name text PRIMARY KEY,"
             f" unspent blob)")
        )

        # Useful for reorg lookups
        await self.unspent_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed on unspent(confirmed)"
        )

        await self.unspent_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on unspent(spent)"
        )

        await self.unspent_db.commit()
        # Lock
        self.lock = asyncio.Lock()  # external
        self.lce_unspent_coins = dict()
        self.head_diffs: Dict[Hash, Dict] = dict()
        return self

    async def close(self):
        await self.unspent_db.close()

    async def _clear_database(self):
        await self.db.execute("DELETE FROM unspent")
        await self.db.commit()

    # TODO take all addition and add them to unspent
    # TODO take all removals and update them as spent
    async def new_lce(self, block: FullBlock):
        print("Not implemented")

    # TODO
    async def new_head(self, head: FullBlock, old: Hash):
        if self.head_diffs[old] is not None:
            del self.head_diffs[old]
        print("new head")

    async def add_unspent(self, unspent: Unspent) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO blocks VALUES(?, ?, ?)",
            (unspent.confirmed_block_index,
             unspent.spent_block_index,
             unspent.coin.name().hex(),
             bytes(unspent)),
        )
        await self.db.commit()
        self.lce_unspent_coins[unspent.coin.name()] = unspent

    # Hit ram chache first, db if it's not in memory
    async def get_unspent(self, coin_name: Hash) -> Optional[Unspent]:
        if self.lce_unspent_coins[coin_name]:
            return self.lce_unspent_coins[coin_name]
        cursor = await self.db.execute(
            "SELECT * from blocks WHERE coin_name=?", (coin_name.hex(),)
        )
        row = await cursor.fetchone()
        if row is not None:
            return Unspent.from_bytes(row[3])
        return None

    # TODO figure out if we want to really delete when doing rollback
    async def rollback_to_block(self, block_index):
        # Update memory cache
        for k, v in self.lce_unspent_coins.items():
            if v.spent_block_index > block_index:
                v.spent_block_index = 0
            if v.confirmed_block_index > block_index:
                del self.lce_unspent_coins[k]
        # Delete from storage
        await self.db.execute("DELETE FROM unspent WHERE confirmed>? ", (block_index,))
        await self.db.execute("UPDATE unspent SET spent = 0 WHERE spent>?", (block_index,))