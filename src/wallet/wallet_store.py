import asyncio
from typing import Dict, Optional, List, Set
from pathlib import Path
import aiosqlite
from src.types.hashable.coin import Coin
from src.types.hashable.coin_record import CoinRecord
from src.wallet.block_record import BlockRecord
from src.types.sized_bytes import bytes32
from src.util.ints import uint32


class WalletStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    db_connection: aiosqlite.Connection
    # Whether or not we are syncing
    lock: asyncio.Lock
    coin_record_cache: Dict[str, CoinRecord]
    cache_size: uint32

    @classmethod
    async def create(cls, db_path: Path, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size

        self.db_connection = await aiosqlite.connect(db_path)
        await self.db_connection.execute(
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
        await self.db_connection.execute(
            f"CREATE TABLE IF NOT EXISTS block_records(header_hash text PRIMARY KEY, height int,"
            f" in_lca_path tinyint, block blob)"
        )

        # Useful for reorg lookups
        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on coin_record(spent)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on coin_record(puzzle_hash)"
        )

        await self.db_connection.commit()
        # Lock
        self.lock = asyncio.Lock()  # external
        self.coin_record_cache = dict()
        return self

    async def close(self):
        await self.db_connection.close()

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM coin_record")
        await cursor.close()
        cursor_2 = await self.db_connection.execute("DELETE FROM block_records")
        await cursor_2.close()
        await self.db_connection.commit()

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: CoinRecord) -> None:
        cursor = await self.db_connection.execute(
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
        await self.db_connection.commit()
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
        cursor = await self.db_connection.execute(
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

        cursor = await self.db_connection.execute(
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

    async def get_unspent_coins(self) -> Dict[bytes32, Coin]:
        """ Returns a dictionary of all unspent coins. """
        result: Dict[bytes32, Coin] = {}
        unspent_coin_records: Set[CoinRecord] = await self.get_coin_records_by_spent(
            False
        )

        for record in unspent_coin_records:
            result[record.name()] = record.coin

        return result

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self, puzzle_hash: bytes32
    ) -> List[CoinRecord]:
        coins = set()
        cursor = await self.db_connection.execute(
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
        c1 = await self.db_connection.execute(
            "DELETE FROM coin_record WHERE confirmed_index>?", (block_index,)
        )
        await c1.close()
        c2 = await self.db_connection.execute(
            "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>?",
            (block_index,),
        )
        await c2.close()
        await self.remove_blocks_from_path(block_index)
        await self.db_connection.commit()

    async def get_lca_path(self) -> Dict[bytes32, BlockRecord]:
        cursor = await self.db_connection.execute(
            "SELECT * from block_records WHERE in_lca_path=1"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        hash_to_br: Dict = {}
        max_height = -1
        for row in rows:
            br = BlockRecord.from_bytes(row[3])
            hash_to_br[bytes.fromhex(row[0])] = br
            assert row[0] == br.header_hash.hex()
            assert row[1] == br.height
            if br.height > max_height:
                max_height = br.height
        # Makes sure there's exactly one block per height
        assert max_height == len(rows) - 1
        return hash_to_br

    async def add_block_record(self, block_record: BlockRecord, in_lca_path: bool):
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO block_records VALUES(?, ?, ?, ?)",
            (
                block_record.header_hash.hex(),
                block_record.height,
                in_lca_path,
                bytes(block_record),
            ),
        )
        await cursor.close()
        await self.db_connection.commit()

    async def get_block_record(self, header_hash: bytes32) -> BlockRecord:
        cursor = await self.db_connection.execute(
            "SELECT * from block_records WHERE header_hash=?", (header_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return BlockRecord.from_bytes(row[1])

    async def add_block_to_path(self, header_hash: bytes32) -> None:
        cursor = await self.db_connection.execute(
            "UPDATE block_records SET in_lca_path=1 WHERE header_hash=?",
            (header_hash.hex(),),
        )
        await cursor.close()
        await self.db_connection.commit()

    async def remove_blocks_from_path(self, from_height: uint32) -> None:
        cursor = await self.db_connection.execute(
            "UPDATE block_records SET in_lca_path=0 WHERE height>?", (from_height,),
        )
        await cursor.close()
        await self.db_connection.commit()
