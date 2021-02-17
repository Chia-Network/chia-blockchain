from typing import Dict, Optional, List
import aiosqlite
from src.types.full_block import FullBlock
from src.types.blockchain_format.coin import Coin
from src.types.coin_record import CoinRecord
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint32, uint64


class CoinStore:
    """
    This object handles CoinRecords in DB.
    A cache is maintained for quicker access to recent coins.
    """

    coin_record_db: aiosqlite.Connection
    coin_record_cache: Dict[str, CoinRecord]
    cache_size: uint32

    @classmethod
    async def create(cls, connection: aiosqlite.Connection, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size
        self.coin_record_db = connection
        await self.coin_record_db.execute(
            (
                "CREATE TABLE IF NOT EXISTS coin_record("
                "coin_name text PRIMARY KEY,"
                " confirmed_index bigint,"
                " spent_index bigint,"
                " spent int,"
                " coinbase int,"
                " puzzle_hash text,"
                " coin_parent text,"
                " amount blob,"
                " timestamp bigint)"
            )
        )

        # Useful for reorg lookups
        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)"
        )

        await self.coin_record_db.execute("CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)")

        await self.coin_record_db.execute("CREATE INDEX IF NOT EXISTS coin_spent on coin_record(spent)")

        await self.coin_record_db.execute("CREATE INDEX IF NOT EXISTS coin_spent on coin_record(puzzle_hash)")

        await self.coin_record_db.commit()
        self.coin_record_cache = dict()
        return self

    async def new_block(self, block: FullBlock):
        """
        Only called for blocks which are blocks (and thus have rewards and transactions)
        """
        if block.is_transaction_block() is False:
            return
        assert block.foliage_transaction_block is not None
        removals, additions = block.tx_removals_and_additions()

        for coin in additions:
            record: CoinRecord = CoinRecord(
                coin,
                block.height,
                uint32(0),
                False,
                False,
                block.foliage_transaction_block.timestamp,
            )
            await self._add_coin_record(record)

        for coin_name in removals:
            await self._set_spent(coin_name, block.height)

        included_reward_coins = block.get_included_reward_coins()
        if block.height == 0:
            assert len(included_reward_coins) == 0
        else:
            assert len(included_reward_coins) >= 2

        for coin in included_reward_coins:
            reward_coin_r: CoinRecord = CoinRecord(
                coin,
                block.height,
                uint32(0),
                False,
                True,
                block.foliage_transaction_block.timestamp,
            )
            await self._add_coin_record(reward_coin_r)

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        if coin_name.hex() in self.coin_record_cache:
            return self.coin_record_cache[coin_name.hex()]
        cursor = await self.coin_record_db.execute("SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
            return CoinRecord(coin, row[1], row[2], row[3], row[4], row[8])
        return None

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(self, puzzle_hash: bytes32) -> List[CoinRecord]:
        coins = set()
        cursor = await self.coin_record_db.execute(
            "SELECT * from coin_record WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))
        return list(coins)

    async def rollback_to_block(self, block_index: int):
        """
        Note that block_index can be negative, in which case everything is rolled back
        """
        # Update memory cache
        delete_queue: bytes32 = []
        for coin_name, coin_record in self.coin_record_cache.items():
            if int(coin_record.spent_block_index) > block_index:
                new_record = CoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    coin_record.spent_block_index,
                    False,
                    coin_record.coinbase,
                    coin_record.timestamp,
                )
                self.coin_record_cache[coin_record.coin.name().hex()] = new_record
            if int(coin_record.confirmed_block_index) > block_index:
                delete_queue.append(coin_name)

        for coin_name in delete_queue:
            del self.coin_record_cache[coin_name]

        # Delete from storage
        c1 = await self.coin_record_db.execute("DELETE FROM coin_record WHERE confirmed_index>?", (block_index,))
        await c1.close()
        c2 = await self.coin_record_db.execute(
            "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>?",
            (block_index,),
        )
        await c2.close()

    async def get_unspent_coin_records(self) -> List[CoinRecord]:
        coins = set()
        cursor = await self.coin_record_db.execute("SELECT * from coin_record WHERE spent=0")
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))
        return list(coins)

    # Store CoinRecord in DB and ram cache
    async def _add_coin_record(self, record: CoinRecord) -> None:
        cursor = await self.coin_record_db.execute(
            "INSERT OR REPLACE INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.coin.name().hex(),
                record.confirmed_block_index,
                record.spent_block_index,
                int(record.spent),
                int(record.coinbase),
                str(record.coin.puzzle_hash.hex()),
                str(record.coin.parent_coin_info.hex()),
                bytes(record.coin.amount),
                record.timestamp,
            ),
        )
        await cursor.close()
        self.coin_record_cache[record.coin.name().hex()] = record
        if len(self.coin_record_cache) > self.cache_size:
            while len(self.coin_record_cache) > self.cache_size:
                first_in = list(self.coin_record_cache.keys())[0]
                del self.coin_record_cache[first_in]

    # Update coin_record to be spent in DB
    async def _set_spent(self, coin_name: bytes32, index: uint32):
        current: Optional[CoinRecord] = await self.get_coin_record(coin_name)
        if current is None:
            return
        spent: CoinRecord = CoinRecord(
            current.coin,
            current.confirmed_block_index,
            index,
            True,
            current.coinbase,
            current.timestamp,
        )  # type: ignore # noqa
        await self._add_coin_record(spent)
