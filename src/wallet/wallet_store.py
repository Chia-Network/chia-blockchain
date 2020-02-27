import asyncio
from typing import Dict, Optional, List, Set
from pathlib import Path
import aiosqlite
from src.types.hashable.coin import Coin
from src.types.hashable.coin_record import CoinRecord
from src.types.sized_bytes import bytes32
from src.util.ints import uint32


class WalletStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    coin_record_db: aiosqlite.Connection
    # Whether or not we are syncing
    sync_mode: bool = False
    lock: asyncio.Lock
    coin_record_cache: Dict[str, CoinRecord]
    cache_size: uint32

    @classmethod
    async def create(cls, db_path: Path, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size

        self.coin_record_db = await aiosqlite.connect(db_path)
        await self.coin_record_db.execute(
            (
                f"CREATE TABLE IF NOT EXISTS coin_record("
                f"coin_name text PRIMARY KEY,"
                f" confirmed_index bigint,"
                f" spent_index bigint,"
                f" spent int,"
                f" coinbase int,"
                f" puzzle_hash text,"
                f" coin_parent text,"
                f" amount bigint)"
            )
        )

        # Useful for reorg lookups
        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)"
        )

        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)"
        )

        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on coin_record(spent)"
        )

        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on coin_record(puzzle_hash)"
        )

        await self.coin_record_db.commit()
        # Lock
        self.lock = asyncio.Lock()  # external
        self.coin_record_cache = dict()
        return self

    async def close(self):
        await self.coin_record_db.close()

    async def _clear_database(self):
        cursor = await self.coin_record_db.execute("DELETE FROM coin_record")
        await cursor.close()
        await self.coin_record_db.commit()

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: CoinRecord) -> None:
        cursor = await self.coin_record_db.execute(
            "INSERT OR REPLACE INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.coin.name().hex(),
                record.confirmed_block_index,
                record.spent_block_index,
                int(record.spent),
                int(record.coinbase),
                str(record.coin.puzzle_hash.hex()),
                str(record.coin.parent_coin_info.hex()),
                record.coin.amount,
            ),
        )
        await cursor.close()
        await self.coin_record_db.commit()
        self.coin_record_cache[record.coin.name().hex()] = record
        if len(self.coin_record_cache) > self.cache_size:
            while len(self.coin_record_cache) > self.cache_size:
                first_in = list(self.coin_record_cache.keys())[0]
                del self.coin_record_cache[first_in]

    # Update coin_record to be spent in DB
    async def set_spent(self, coin_name: bytes32, index: uint32):
        current: Optional[CoinRecord] = await self.get_coin_record(coin_name)
        if current is None:
            return
        spent: CoinRecord = CoinRecord(
            current.coin, current.confirmed_block_index, index, True, current.coinbase,
        )
        await self.add_coin_record(spent)

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        if coin_name.hex() in self.coin_record_cache:
            return self.coin_record_cache[coin_name.hex()]
        cursor = await self.coin_record_db.execute(
            "SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            return CoinRecord(coin, row[1], row[2], row[3], row[4])
        return None

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_spent(self, spent: bool) -> Set[CoinRecord]:
        coins = set()

        cursor = await self.coin_record_db.execute(
            "SELECT * from coin_record WHERE spent=?", (int(spent),)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4]))
        return coins

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self, puzzle_hash: bytes32
    ) -> List[CoinRecord]:
        coins = set()
        cursor = await self.coin_record_db.execute(
            "SELECT * from coin_record WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4]))
        return list(coins)

    async def rollback_lca_to_block(self, block_index):
        # Update memory cache
        delete_queue: bytes32 = []
        for coin_name, coin_record in self.coin_record_cache.items():
            if coin_record.spent_block_index > block_index:
                new_record = CoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    coin_record.spent_block_index,
                    False,
                    coin_record.coinbase,
                )
                self.coin_record_cache[coin_record.coin.name().hex()] = new_record
            if coin_record.confirmed_block_index > block_index:
                delete_queue.append(coin_name)

        for coin_name in delete_queue:
            del self.coin_record_cache[coin_name]

        # Delete from storage
        c1 = await self.coin_record_db.execute(
            "DELETE FROM coin_record WHERE confirmed_index>?", (block_index,)
        )
        await c1.close()
        c2 = await self.coin_record_db.execute(
            "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>?",
            (block_index,),
        )
        await c2.close()
        await self.coin_record_db.commit()
