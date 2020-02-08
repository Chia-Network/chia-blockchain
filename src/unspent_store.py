import asyncio
from typing import Dict, Optional, List
from pathlib import Path
import aiosqlite
from src.types.full_block import FullBlock
from src.types.hashable.Coin import Coin
from src.types.hashable.CoinRecord import CoinRecord
from src.types.sized_bytes import bytes32
from src.types.header import Header
from src.util.ints import uint32, uint8


class DiffStore:
    header: Header
    diffs: Dict[bytes32, CoinRecord]

    @staticmethod
    async def create(header: Header, diffs: Dict[bytes32, CoinRecord]):
        self = DiffStore()
        self.header = header
        self.diffs = diffs
        return self


class UnspentStore:
    """
    This object handles unspent coins in DB.
    Coins from genesis to LCA are stored on disk db, coins from lca to head are stored in DiffStore object for each tip.
    When blockchain notifies UnspentStore of new LCA, LCA is added to the disk db,
    DiffStores are updated/recreated. (managed by blockchain.py)
    """

    unspent_db: aiosqlite.Connection
    # Whether or not we are syncing
    sync_mode: bool = False
    lock: asyncio.Lock
    lca_unspent_coins: Dict[str, CoinRecord]
    head_diffs: Dict[bytes32, DiffStore]
    cache_size: uint32

    @classmethod
    async def create(cls, db_path: Path, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size
        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.unspent_db = await aiosqlite.connect(db_path)
        await self.unspent_db.execute(
            (
                f"CREATE TABLE IF NOT EXISTS unspent("
                f"coin_name text PRIMARY KEY,"
                f" confirmed_index bigint,"
                f" spent_index bigint,"
                f" spent int,"
                f" coinbase int,"
                f" puzzle_hash text,"
                f" unspent blob)"
            )
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

        await self.unspent_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on unspent(puzzle_hash)"
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

    async def add_lcas(self, blocks: List[FullBlock]):
        for block in blocks:
            await self.new_lca(block)

    async def new_lca(self, block: FullBlock):
        removals, additions = await block.tx_removals_and_additions()

        for coin_name in removals:
            await self.set_spent(coin_name, block.height)

        for coin in additions:
            unspent: CoinRecord = CoinRecord(coin, block.height, 0, 0, 0)  # type: ignore # noqa
            await self.add_unspent(unspent)

        coinbase: CoinRecord = CoinRecord(block.body.coinbase, block.height, 0, 0, 1)  # type: ignore # noqa
        fees_coin: CoinRecord = CoinRecord(block.body.fees_coin, block.height, 0, 0, 1)  # type: ignore # noqa
        await self.add_unspent(coinbase)
        await self.add_unspent(fees_coin)

    def nuke_diffs(self):
        self.head_diffs.clear()

    # Received new tip, just update diffs
    async def new_heads(self, blocks: List[FullBlock]):
        last: FullBlock = blocks[-1]
        diff_store: DiffStore = await DiffStore.create(last.header, dict())

        block: FullBlock
        for block in blocks:
            removals, additions = await block.tx_removals_and_additions()
            await self.add_diffs(removals, additions, block, diff_store)

        self.head_diffs[last.header_hash] = diff_store

    async def add_diffs(
        self,
        removals: List[bytes32],
        additions: List[Coin],
        block: FullBlock,
        diff_store: DiffStore,
    ):

        for coin_name in removals:
            removed: Optional[CoinRecord] = None
            if coin_name.hex() in diff_store.diffs:
                removed = diff_store.diffs[coin_name.hex()]
            if removed is None:
                removed = await self.get_coin_record(coin_name)
            if removed is None:
                raise Exception
            spent = CoinRecord(
                removed.coin,
                removed.confirmed_block_index,
                block.height,
                uint8(1),
                removed.coinbase,
            )  # type: ignore # noqa
            diff_store.diffs[spent.name.hex()] = spent

        for coin in additions:
            added: CoinRecord = CoinRecord(coin, block.height, 0, 0, 0)  # type: ignore # noqa
            diff_store.diffs[added.name.hex()] = added

        coinbase: CoinRecord = CoinRecord(block.body.coinbase, block.height, 0, 0, 1)  # type: ignore # noqa
        diff_store.diffs[coinbase.name.hex()] = coinbase
        fees_coin: CoinRecord = CoinRecord(block.body.fees_coin, block.height, 0, 0, 1)  # type: ignore # noqa
        diff_store.diffs[fees_coin.name.hex()] = fees_coin

    # Store unspent in DB and ram cache
    async def add_unspent(self, unspent: CoinRecord) -> None:
        cursor = await self.unspent_db.execute(
            "INSERT OR REPLACE INTO unspent VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                unspent.coin.name().hex(),
                unspent.confirmed_block_index,
                unspent.spent_block_index,
                int(unspent.spent),
                int(unspent.coinbase),
                str(unspent.coin.puzzle_hash.hex()),
                bytes(unspent),
            ),
        )
        await cursor.close()
        await self.unspent_db.commit()
        self.lca_unspent_coins[unspent.coin.name().hex()] = unspent
        if len(self.lca_unspent_coins) > self.cache_size:
            while len(self.lca_unspent_coins) > self.cache_size:
                first_in = list(self.lca_unspent_coins.keys())[0]
                del self.lca_unspent_coins[first_in]

    # Update unspent to be spent in DB
    async def set_spent(self, coin_name: bytes32, index: uint32):
        current: Optional[CoinRecord] = await self.get_coin_record(coin_name)
        if current is None:
            return
        spent: CoinRecord = CoinRecord(
            current.coin,
            current.confirmed_block_index,
            index,
            uint8(1),
            current.coinbase,
        )  # type: ignore # noqa
        await self.add_unspent(spent)

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(
        self, coin_name: bytes32, header: Header = None
    ) -> Optional[CoinRecord]:
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
            return CoinRecord(Coin.from_bytes(row[6]), row[1], row[2], row[3], row[4])
        return None

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self, puzzle_hash: bytes32, header: Header = None
    ) -> List[CoinRecord]:
        coins = set()
        if header is not None and header.header_hash in self.head_diffs:
            diff_store = self.head_diffs[header.header_hash]
            for _, record in diff_store.diffs.items():
                if record.coin.puzzle_hash == puzzle_hash:
                    coins.add(record)
        cursor = await self.unspent_db.execute(
            "SELECT * from unspent WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coins.add(
                CoinRecord(Coin.from_bytes(row[6]), row[1], row[2], row[3], row[4])
            )
        return list(coins)

    # TODO figure out if we want to really delete when doing rollback
    async def rollback_lca_to_block(self, block_index):
        # Update memory cache
        delete_queue: bytes32 = []
        for coin_name, coin_record in self.lca_unspent_coins.items():
            if coin_record.spent_block_index > block_index:
                new_unspent = CoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    coin_record.spent_block_index,
                    uint8(0),
                    coin_record.coinbase,
                )
                self.lca_unspent_coins[coin_record.coin.name().hex()] = new_unspent
            if coin_record.confirmed_block_index > block_index:
                delete_queue.append(coin_name)

        for coin_name in delete_queue:
            del self.lca_unspent_coins[coin_name]

        # Delete from storage
        c1 = await self.unspent_db.execute(
            "DELETE FROM unspent WHERE confirmed_index>?", (block_index,)
        )
        await c1.close()
        c2 = await self.unspent_db.execute(
            "UPDATE unspent SET spent_index = 0, spent = 0 WHERE spent_index>?",
            (block_index,),
        )
        await c2.close()
        await self.unspent_db.commit()
