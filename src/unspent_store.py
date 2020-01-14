import asyncio
from typing import Dict, Optional, List

import aiosqlite

from src.consensus.constants import constants as consensus_constants
from src.types.full_block import FullBlock
from src.types.hashable import Hash, Unspent, Coin, CoinName
from src.util.chain_utils import name_puzzle_conditions_list
from src.util.consensus import created_outputs_for_conditions_dict
from src.util.ints import uint32


def additions_for_npc(npc_list) -> List[Coin]:
    additions: List[Coin] = []
    for coin_name, puzzle_hash, conditions_dict in npc_list:
        for coin in created_outputs_for_conditions_dict(conditions_dict, coin_name):
            additions.append(coin)

    return additions


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
             f"confirmed_index bigint,"
             f" spent_index bigint,"
             f" spent int,"
             f" coin_name text PRIMARY KEY,"
             f" unspent blob)")
        )

        # Useful for reorg lookups
        await self.unspent_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed_index on unspent(confirmed_index)"
        )

        await self.unspent_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent_index on unspent(spent_index)"
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

    async def new_lca(self, block: FullBlock):
        print("Not implemented")
        coinbase: Unspent = Unspent(block.body.coinbase, block.height, 0, False)
        fee: Unspent = Unspent(block.body.fees_coin, block.height, 0, False)

        # Add coinbase and fee coin
        await self.add_unspent(coinbase)
        await self.add_unspent(fee)

        # Add transacitions
        if block.body.transactions is not None:
            # ensure block program generates solutions
            # This should never throw here, block must be valid if it comes to here
            npc_list = name_puzzle_conditions_list(block.body.transactions)
            # build removals list
            removals = tuple(_[0] for _ in npc_list)
            additions: List[Coin] = additions_for_npc(npc_list)
            for coin_name in removals:
                await self.set_spent(coin_name, block.height)
            for coin in additions:
                unspent: Unspent = Unspent(coin, block.height, 0, False)
                await self.add_unspent(unspent)

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
             int(unspent.spent),
             bytes(unspent)),
        )
        await self.db.commit()
        self.lce_unspent_coins[unspent.coin.name()] = unspent

    async def set_spent(self, coin_name: Hash, index: uint32):
        spent: Unspent = await self.get_unspent(coin_name)
        spent.spent = True
        spent.spent_block_index = index
        await self.add_unspent(spent)

    # Hit ram cache first, db if it's not in memory
    async def get_unspent(self, coin_name: Hash) -> Optional[Unspent]:
        if self.lce_unspent_coins[coin_name.hex()]:
            return self.lce_unspent_coins[coin_name.hex()]
        cursor = await self.db.execute(
            "SELECT * from blocks WHERE coin_name=?", (coin_name.hex(),)
        )
        row = await cursor.fetchone()
        if row is not None:
            return Unspent.from_bytes(row[4])
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
        await self.db.execute("DELETE FROM unspent WHERE confirmed_index>?", (block_index,))
        await self.db.execute("UPDATE unspent SET spent_index = 0, spent = 0 WHERE spent_index>?", (block_index,))
