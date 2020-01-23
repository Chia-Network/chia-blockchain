import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
import aiosqlite
from src.types.full_block import FullBlock
from src.types.hashable import Hash, Unspent, Coin, CoinName
from src.types.header_block import HeaderBlock
from src.util.chain_utils import name_puzzle_conditions_list
from src.util.consensus import created_outputs_for_conditions_dict
from src.util.ints import uint32


def additions_for_npc(npc_list) -> List[Coin]:
    additions: List[Coin] = []

    for coin_name, puzzle_hash, conditions_dict in npc_list:
        for coin in created_outputs_for_conditions_dict(conditions_dict, coin_name):
            additions.append(coin)

    return additions


def removals_and_additions(block: FullBlock) -> Tuple[List[Hash], List[Coin]]:
    removals: List[Hash] = []
    additions: List[Coin] = []

    additions.append(block.body.coinbase)
    additions.append(block.body.fees_coin)

    if block.body.transactions is not None:
        # ensure block program generates solutions
        # This should never throw here, block must be valid if it comes to here
        npc_list = name_puzzle_conditions_list(block.body.transactions)
        # build removals list
        for coin_name, ph, con in npc_list:
            removals.append(coin_name)

        additions.extend(additions_for_npc(npc_list))

    return removals, additions


class DiffStore:
    header: HeaderBlock
    diffs: Dict[CoinName, Unspent]

    @staticmethod
    async def create(head: HeaderBlock, diffs: Dict[CoinName, Unspent]):
        self = DiffStore()
        self.header = head
        self.diffs = diffs
        return self


class UnspentStore:
    db_name: str
    unspent_db: aiosqlite.Connection
    # Whether or not we are syncing
    sync_mode: bool = False
    lock: asyncio.Lock
    # TODO set the size limit of ram cache
    lca_unspent_coins: Dict[str, Unspent]
    head_diffs: Dict[Hash, DiffStore]

    @classmethod
    async def create(cls, db_name: str):
        self = cls()
        self.db_name = db_name

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.unspent_db = await aiosqlite.connect(self.db_name)
        await self.unspent_db.execute(
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
        self.lca_unspent_coins = dict()
        self.head_diffs = dict()
        return self

    async def close(self):
        await self.unspent_db.close()

    async def _clear_database(self):
        await self.unspent_db.execute("DELETE FROM unspent")
        await self.unspent_db.commit()

    async def add_lcas(self, blocks: [FullBlock]):
        for block in blocks:
            await self.new_lca(block)

    async def new_lca(self, block: FullBlock):
        removals, additions = removals_and_additions(block)

        for coin_name in removals:
            await self.set_spent(coin_name, block.height)

        for coin in additions:
            unspent: Unspent = Unspent(coin, block.height, 0, 0)
            await self.add_unspent(unspent)

    def nuke_diffs(self):
        self.head_diffs = dict()

    # Received new tip, just update diffs
    async def new_heads(self, blocks: [FullBlock]):
        last: FullBlock = blocks[-1]
        diff_store: DiffStore = await DiffStore.create(last.header_block, dict())

        for block in blocks:
            removals, additions = removals_and_additions(block)
            await self.add_diffs(removals, additions, block, diff_store)

        self.head_diffs[last.header_hash] = diff_store

    async def add_diffs(self, removals: List[Hash], additions: List[Coin],
                        block: FullBlock, diff_store: DiffStore):

        for coin_name in removals:
            removed: Unspent = diff_store.diffs[coin_name]
            if removed is None:
                removed = await self.get_unspent(coin_name)
            spent = Unspent(removed.coin, removed.confirmed_block_index,
                            block.height, 1)
            diff_store.diffs[spent.name()] = spent

        for coin in additions:
            added: Unspent = Unspent(coin, block.height, 0, 0)
            diff_store.diffs[added.name()] = added

    # Store unspent in DB and ram cache
    async def add_unspent(self, unspent: Unspent) -> None:
        await self.unspent_db.execute(
            "INSERT OR REPLACE INTO unspent VALUES(?, ?, ?, ?, ?)",
            (unspent.confirmed_block_index,
             unspent.spent_block_index,
             unspent.coin.name().hex(),
             int(unspent.spent),
             bytes(unspent)),
        )
        await self.unspent_db.commit()
        self.lca_unspent_coins[unspent.coin.name().hex()] = unspent

    # Update unspent to be spent in DB
    async def set_spent(self, coin_name: Hash, index: uint32):
        current: Unspent = await self.get_unspent(coin_name)
        spent: Unspent = Unspent(current.coin, current.confirmed_block_index,
                                 index, 1)
        await self.add_unspent(spent)

    # Checks DB and DiffStores for unspent with coin_name and returns it
    async def get_unspent(self, coin_name: CoinName, header: HeaderBlock = None) -> Optional[Unspent]:
        if header is not None:
            diff_store = self.head_diffs[header]
            if coin_name in diff_store.diffs:
                return diff_store[coin_name.hex()]
        if coin_name.hex() in self.lca_unspent_coins:
            return self.lca_unspent_coins[coin_name.hex()]
        cursor = await self.unspent_db.execute(
            "SELECT * from unspent WHERE coin_name=?", (coin_name.hex(),)
        )
        row = await cursor.fetchone()
        if row is not None:
            return Unspent.from_bytes(row[4])
        return None

    # TODO figure out if we want to really delete when doing rollback
    async def rollback_lca_to_block(self, block_index):
        # Update memory cache
        for k in list(self.lca_unspent_coins.keys()):
            v = self.lca_unspent_coins[k]
            if v.spent_block_index > block_index:
                new_unspent = Unspent(v.coin, v.confirmed_block_index,
                                      v.spent_block_index, 0)
                self.lca_unspent_coins[v.coin.name().hex()] = new_unspent
            if v.confirmed_block_index > block_index:
                del self.lca_unspent_coins[k]
        # Delete from storage
        await self.unspent_db.execute("DELETE FROM unspent WHERE confirmed_index>?", (block_index,))
        await self.unspent_db.execute("UPDATE unspent SET spent_index = 0, spent = 0 WHERE spent_index>?", (block_index,))
