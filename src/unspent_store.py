import asyncio
from typing import Dict, Optional, List
import aiosqlite
from src.types.full_block import FullBlock
from src.types.hashable import Hash, Unspent, Coin, CoinName
from src.types.header_block import HeaderBlock
from src.util.ints import uint32

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
             f"coin_name text PRIMARY KEY,"
             f" confirmed_index bigint,"
             f" spent_index bigint,"
             f" spent int,"
             f" coinbase int,"
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
        cursor = await self.unspent_db.execute("DELETE FROM unspent")
        await cursor.close()
        await self.unspent_db.commit()

    async def add_lcas(self, blocks: [FullBlock]):
        for block in blocks:
            await self.new_lca(block)

    async def new_lca(self, block: FullBlock):
        removals, additions = block.tx_removals_and_additions()

        for coin_name in removals:
            await self.set_spent(coin_name, block.height)

        for coin in additions:
            unspent: Unspent = Unspent(coin, block.height, 0, 0, 0)
            await self.add_unspent(unspent)

        coinbase: Unspent = Unspent(block.body.coinbase, block.height, 0, 0, 1)
        fees_coin: Unspent = Unspent(block.body.fees_coin, block.height, 0, 0, 1)
        await self.add_unspent(coinbase)
        await self.add_unspent(fees_coin)

    def nuke_diffs(self):
        self.head_diffs = dict()

    # Received new tip, just update diffs
    async def new_heads(self, blocks: [FullBlock]):
        last: FullBlock = blocks[-1]
        diff_store: DiffStore = await DiffStore.create(last.header_block, dict())

        block: FullBlock
        for block in blocks:
            removals, additions = block.tx_removals_and_additions()
            await self.add_diffs(removals, additions, block, diff_store)

        self.head_diffs[last.header_hash] = diff_store

    async def add_diffs(self, removals: List[Hash], additions: List[Coin],
                        block: FullBlock, diff_store: DiffStore):

        for coin_name in removals:
            removed: Unspent = diff_store.diffs[coin_name.hex()]
            if removed is None:
                removed = await self.get_unspent(coin_name)
            spent = Unspent(removed.coin, removed.confirmed_block_index,
                            block.height, 1, removed.coinbase)
            diff_store.diffs[spent.name.hex()] = spent

        for coin in additions:
            added: Unspent = Unspent(coin, block.height, 0, 0, 1)
            diff_store.diffs[added.name.hex()] = added

    # Store unspent in DB and ram cache
    async def add_unspent(self, unspent: Unspent) -> None:
        cursor = await self.unspent_db.execute(
            "INSERT OR REPLACE INTO unspent VALUES(?, ?, ?, ?, ?, ?)",
            (unspent.coin.name().hex(),
             unspent.confirmed_block_index,
             unspent.spent_block_index,
             int(unspent.spent),
             int(unspent.coinbase),
             bytes(unspent)),
        )
        await cursor.close()
        await self.unspent_db.commit()
        self.lca_unspent_coins[unspent.coin.name().hex()] = unspent

    # Update unspent to be spent in DB
    async def set_spent(self, coin_name: Hash, index: uint32):
        current: Unspent = await self.get_unspent(coin_name)
        spent: Unspent = Unspent(current.coin, current.confirmed_block_index,
                                 index, 1, current.coinbase)
        await self.add_unspent(spent)

    # Checks DB and DiffStores for unspent with coin_name and returns it
    async def get_unspent(self, coin_name: CoinName, header: HeaderBlock = None) -> Optional[Unspent]:
        if header is not None and header.header_hash in self.head_diffs:
            diff_store = self.head_diffs[header.header_hash]
            if coin_name.hex() in diff_store.diffs:
                return diff_store.diffs[coin_name.hex()]
        if coin_name.hex() in self.lca_unspent_coins:
            return self.lca_unspent_coins[coin_name.hex()]
        cursor = await self.unspent_db.execute(
            "SELECT * from unspent WHERE coin_name=?", (coin_name.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
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
                                      v.spent_block_index, 0, v.coinbase)
                self.lca_unspent_coins[v.coin.name().hex()] = new_unspent
            if v.confirmed_block_index > block_index:
                del self.lca_unspent_coins[k]
        # Delete from storage
        c1 = await self.unspent_db.execute("DELETE FROM unspent WHERE confirmed_index>?", (block_index,))
        await c1.close()
        c2 = await self.unspent_db.execute("UPDATE unspent SET spent_index = 0, spent = 0 WHERE spent_index>?", (block_index,))
        await c2.close()
        await self.unspent_db.commit()