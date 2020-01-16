import asyncio
from typing import Dict, Optional, List, Tuple
import aiosqlite
from src.types.full_block import FullBlock
from src.types.hashable import Hash, Unspent, Coin
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
    diffs: Dict[Hash, Unspent]


class UnspentStore:
    db_name: str
    unspent_db: aiosqlite.Connection
    # Whether or not we are syncing
    sync_mode: bool = False
    lock: asyncio.Lock
    # TODO set the size limit of ram cache
    lce_unspent_coins: Dict
    head_diffs: Dict[HeaderBlock, DiffStore]

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
        self.lce_unspent_coins = dict()
        self.head_diffs = dict()
        return self

    async def close(self):
        await self.unspent_db.close()

    async def _clear_database(self):
        await self.unspent_db.execute("DELETE FROM unspent")
        await self.unspent_db.commit()

    async def new_lca(self, block: FullBlock):
        removals, additions = removals_and_additions(block)

        for coin_name in removals:
            await self.set_spent(coin_name, block.height)

        for coin in additions:
            unspent: Unspent = Unspent(coin, block.height, 0, 0)
            await self.add_unspent(unspent)

    # Received new tip, just update diffs
    async def new_head(self, head: FullBlock, old: Optional[HeaderBlock]):
        removals, additions = removals_and_additions(head)
        # New Head nothing is being replaced
        if old is None:
            await self.add_diffs(removals, additions, head)

        if self.head_diffs[old] is not None:
            # Old head is being extended, add diffs
            if head.prev_header_hash == old.header_hash:
                old_diff = self.head_diffs.pop(old)
                await self.add_diffs(removals, additions, head, old_diff)

            # Old head is being replaced
            else:
                del self.head_diffs[old]
                await self.add_diffs(removals, additions, head)

    async def add_diffs(self, removals: List[Hash], additions: List[Coin],
                        head: FullBlock, diff_store: DiffStore = None):
        if diff_store is None:
            diff_store: DiffStore = DiffStore(head.header_block, dict())

        for coin_name in removals:
            removed: Unspent = diff_store.diffs[coin_name]
            if removed is None:
                removed = await self.get_unspent(coin_name)
            spent = Unspent(removed.coin, removed.confirmed_block_index,
                            head.height, 1)
            diff_store.diffs[spent.name()] = spent

        for coin in additions:
            added: Unspent = Unspent(coin, head.height, 0, 0)
            diff_store.diffs[added.name()] = added

        diff_store.header = head.header_block
        self.head_diffs[head.header_block] = diff_store

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
        self.lce_unspent_coins[unspent.coin.name().hex()] = unspent

    # Update unspent to be spent
    async def set_spent(self, coin_name: Hash, index: uint32):
        current: Unspent = await self.get_unspent(coin_name)
        spent: Unspent = Unspent(current.coin, current.confirmed_block_index,
                                 index, 1)
        await self.add_unspent(spent)

    # Hit ram cache first, db if it's not in memory
    async def get_unspent(self, coin_name: Hash) -> Optional[Unspent]:
        if self.lce_unspent_coins[coin_name.hex()]:
            return self.lce_unspent_coins[coin_name.hex()]
        cursor = await self.unspent_db.execute(
            "SELECT * from unspent WHERE coin_name=?", (coin_name.hex(),)
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
        await self.unspent_db.execute("DELETE FROM unspent WHERE confirmed_index>?", (block_index,))
        await self.unspent_db.execute("UPDATE unspent SET spent_index = 0, spent = 0 WHERE spent_index>?", (block_index,))
