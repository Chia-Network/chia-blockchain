import logging
from time import time
from typing import Dict, List, Optional, Set

import aiosqlite

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64
from chia.util.lru_cache import LRUCache

log = logging.getLogger(__name__)


class CoinStore:
    """
    This object handles CoinRecords in DB.
    A cache is maintained for quicker access to recent coins.
    """

    coin_record_db: aiosqlite.Connection
    coin_record_cache: LRUCache
    cache_size: uint32
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper, cache_size: uint32 = uint32(60000)):
        self = cls()

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper
        self.coin_record_db = db_wrapper.db
        # the coin_name is unique in this table because the CoinStore always
        # only represent a single peak
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

        # earlier versions of chia created this index despite no lookups needing
        # it. For now, just don't create it for new installs. In the future we
        # may remove the index from existing installations as well
        # await self.coin_record_db.execute("DROP INDEX IF EXISTS coin_spent")

        await self.coin_record_db.execute("CREATE INDEX IF NOT EXISTS coin_puzzle_hash on coin_record(puzzle_hash)")

        await self.coin_record_db.execute("CREATE INDEX IF NOT EXISTS coin_parent_index on coin_record(coin_parent)")

        await self.coin_record_db.commit()
        self.coin_record_cache = LRUCache(cache_size)
        return self

    async def new_block(
        self,
        height: uint32,
        timestamp: uint64,
        included_reward_coins: Set[Coin],
        tx_additions: List[Coin],
        tx_removals: List[bytes32],
    ) -> List[CoinRecord]:
        """
        Only called for blocks which are blocks (and thus have rewards and transactions)
        Returns a list of the CoinRecords that were added by this block
        """

        start = time()

        additions = []

        for coin in tx_additions:
            record: CoinRecord = CoinRecord(
                coin,
                height,
                uint32(0),
                False,
                False,
                timestamp,
            )
            additions.append(record)

        if height == 0:
            assert len(included_reward_coins) == 0
        else:
            assert len(included_reward_coins) >= 2

        for coin in included_reward_coins:
            reward_coin_r: CoinRecord = CoinRecord(
                coin,
                height,
                uint32(0),
                False,
                True,
                timestamp,
            )
            additions.append(reward_coin_r)

        await self._add_coin_records(additions)
        await self._set_spent(tx_removals, height)

        end = time()
        log.log(
            logging.WARNING if end - start > 10 else logging.DEBUG,
            f"It took {end - start:0.2f}s to apply {len(tx_additions)} additions and "
            + f"{len(tx_removals)} removals to the coin store. Make sure "
            + "blockchain database is on a fast drive",
        )

        return additions

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        cached = self.coin_record_cache.get(coin_name)
        if cached is not None:
            return cached
        cursor = await self.coin_record_db.execute("SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            coin = self.row_to_coin(row)
            record = CoinRecord(coin, row[1], row[2], row[3], row[4], row[8])
            self.coin_record_cache.put(record.coin.name(), record)
            return record
        return None

    async def get_coins_added_at_height(self, height: uint32) -> List[CoinRecord]:
        cursor = await self.coin_record_db.execute("SELECT * from coin_record WHERE confirmed_index=?", (height,))
        rows = await cursor.fetchall()
        await cursor.close()
        coins = []
        for row in rows:
            coin = self.row_to_coin(row)
            coins.append(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))
        return coins

    async def get_coins_removed_at_height(self, height: uint32) -> List[CoinRecord]:
        # Special case to avoid querying all unspent coins (spent_index=0)
        if height == 0:
            return []
        cursor = await self.coin_record_db.execute("SELECT * from coin_record WHERE spent_index=?", (height,))
        rows = await cursor.fetchall()
        await cursor.close()
        coins = []
        for row in rows:
            spent: bool = bool(row[3])
            if spent:
                coin = self.row_to_coin(row)
                coin_record = CoinRecord(coin, row[1], row[2], spent, row[4], row[8])
                coins.append(coin_record)
        return coins

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self,
        include_spent_coins: bool,
        puzzle_hash: bytes32,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2 ** 32) - 1),
    ) -> List[CoinRecord]:

        coins = set()
        cursor = await self.coin_record_db.execute(
            f"SELECT * from coin_record INDEXED BY coin_puzzle_hash WHERE puzzle_hash=? "
            f"AND confirmed_index>=? AND confirmed_index<? "
            f"{'' if include_spent_coins else 'AND spent=0'}",
            (puzzle_hash.hex(), start_height, end_height),
        )
        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))
        return list(coins)

    async def get_coin_records_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2 ** 32) - 1),
    ) -> List[CoinRecord]:
        if len(puzzle_hashes) == 0:
            return []

        coins = set()
        puzzle_hashes_db = tuple([ph.hex() for ph in puzzle_hashes])
        cursor = await self.coin_record_db.execute(
            f"SELECT * from coin_record INDEXED BY coin_puzzle_hash "
            f'WHERE puzzle_hash in ({"?," * (len(puzzle_hashes) - 1)}?) '
            f"AND confirmed_index>=? AND confirmed_index<? "
            f"{'' if include_spent_coins else 'AND spent=0'}",
            puzzle_hashes_db + (start_height, end_height),
        )

        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))
        return list(coins)

    async def get_coin_records_by_names(
        self,
        include_spent_coins: bool,
        names: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2 ** 32) - 1),
    ) -> List[CoinRecord]:
        if len(names) == 0:
            return []

        coins = set()
        names_db = tuple([name.hex() for name in names])
        cursor = await self.coin_record_db.execute(
            f'SELECT * from coin_record WHERE coin_name in ({"?," * (len(names) - 1)}?) '
            f"AND confirmed_index>=? AND confirmed_index<? "
            f"{'' if include_spent_coins else 'AND spent=0'}",
            names_db + (start_height, end_height),
        )
        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))

        return list(coins)

    def row_to_coin(self, row) -> Coin:
        return Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))

    def row_to_coin_state(self, row):
        coin = self.row_to_coin(row)
        spent_h = None
        if row[3]:
            spent_h = row[2]
        return CoinState(coin, spent_h, row[1])

    async def get_coin_states_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2 ** 32) - 1),
    ) -> List[CoinState]:
        if len(puzzle_hashes) == 0:
            return []

        coins = set()
        puzzle_hashes_db = tuple([ph.hex() for ph in puzzle_hashes])
        cursor = await self.coin_record_db.execute(
            f'SELECT * from coin_record WHERE puzzle_hash in ({"?," * (len(puzzle_hashes) - 1)}?) '
            f"AND confirmed_index>=? AND confirmed_index<? "
            f"{'' if include_spent_coins else 'AND spent=0'}",
            puzzle_hashes_db + (start_height, end_height),
        )

        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coins.add(self.row_to_coin_state(row))

        return list(coins)

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2 ** 32) - 1),
    ) -> List[CoinRecord]:
        if len(parent_ids) == 0:
            return []

        coins = set()
        parent_ids_db = tuple([pid.hex() for pid in parent_ids])
        cursor = await self.coin_record_db.execute(
            f'SELECT * from coin_record WHERE coin_parent in ({"?," * (len(parent_ids) - 1)}?) '
            f"AND confirmed_index>=? AND confirmed_index<? "
            f"{'' if include_spent_coins else 'AND spent=0'}",
            parent_ids_db + (start_height, end_height),
        )

        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))
        return list(coins)

    async def get_coin_state_by_ids(
        self,
        include_spent_coins: bool,
        coin_ids: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2 ** 32) - 1),
    ) -> List[CoinState]:
        if len(coin_ids) == 0:
            return []

        coins = set()
        coin_ids_db = tuple([pid.hex() for pid in coin_ids])
        cursor = await self.coin_record_db.execute(
            f'SELECT * from coin_record WHERE coin_name in ({"?," * (len(coin_ids) - 1)}?) '
            f"AND confirmed_index>=? AND confirmed_index<? "
            f"{'' if include_spent_coins else 'AND spent=0'}",
            coin_ids_db + (start_height, end_height),
        )

        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coins.add(self.row_to_coin_state(row))
        return list(coins)

    async def rollback_to_block(self, block_index: int) -> List[CoinRecord]:
        """
        Note that block_index can be negative, in which case everything is rolled back
        Returns the list of coin records that have been modified
        """
        # Update memory cache
        delete_queue: bytes32 = []
        for coin_name, coin_record in list(self.coin_record_cache.cache.items()):
            if int(coin_record.spent_block_index) > block_index:
                new_record = CoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    uint32(0),
                    False,
                    coin_record.coinbase,
                    coin_record.timestamp,
                )
                self.coin_record_cache.put(coin_record.coin.name(), new_record)
            if int(coin_record.confirmed_block_index) > block_index:
                delete_queue.append(coin_name)

        for coin_name in delete_queue:
            self.coin_record_cache.remove(coin_name)

        coin_changes: Dict[bytes32, CoinRecord] = {}
        cursor_deleted = await self.coin_record_db.execute(
            "SELECT * FROM coin_record WHERE confirmed_index>?", (block_index,)
        )
        rows = await cursor_deleted.fetchall()
        for row in rows:
            coin = self.row_to_coin(row)
            record = CoinRecord(coin, uint32(0), row[2], row[3], row[4], uint64(0))
            coin_changes[record.name] = record
        await cursor_deleted.close()

        # Delete from storage
        c1 = await self.coin_record_db.execute("DELETE FROM coin_record WHERE confirmed_index>?", (block_index,))
        await c1.close()

        cursor_unspent = await self.coin_record_db.execute(
            "SELECT * FROM coin_record WHERE confirmed_index>?", (block_index,)
        )
        rows = await cursor_unspent.fetchall()
        for row in rows:
            coin = self.row_to_coin(row)
            record = CoinRecord(coin, row[1], uint32(0), False, row[4], row[8])
            if record.name not in coin_changes:
                coin_changes[record.name] = record
        await cursor_unspent.close()

        c2 = await self.coin_record_db.execute(
            "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>?",
            (block_index,),
        )
        await c2.close()
        return list(coin_changes.values())

    # Store CoinRecord in DB and ram cache
    async def _add_coin_records(self, records: List[CoinRecord]) -> None:

        values = []
        for record in records:
            self.coin_record_cache.put(record.coin.name(), record)
            values.append(
                (
                    record.coin.name().hex(),
                    record.confirmed_block_index,
                    record.spent_block_index,
                    int(record.spent),
                    int(record.coinbase),
                    record.coin.puzzle_hash.hex(),
                    record.coin.parent_coin_info.hex(),
                    bytes(record.coin.amount),
                    record.timestamp,
                )
            )

        cursor = await self.coin_record_db.executemany(
            "INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        await cursor.close()

    # Update coin_record to be spent in DB
    async def _set_spent(self, coin_names: List[bytes32], index: uint32):

        # if this coin is in the cache, mark it as spent in there
        updates = []
        for coin_name in coin_names:
            r = self.coin_record_cache.get(coin_name)
            if r is not None:
                self.coin_record_cache.put(
                    r.name, CoinRecord(r.coin, r.confirmed_block_index, index, True, r.coinbase, r.timestamp)
                )
            updates.append((index, coin_name.hex()))

        await self.coin_record_db.executemany(
            "UPDATE OR FAIL coin_record SET spent=1,spent_index=? WHERE coin_name=?", updates
        )

    async def get_unspent_coins_before_height(self, puzzle_hash: bytes, height: uint32) -> List[CoinRecord]:
        coins = set()
        cursor = await self.coin_record_db.execute(
            "SELECT * from coin_record INDEXED BY coin_puzzle_hash WHERE puzzle_hash=? "
            "AND confirmed_index<? "
            "AND (spent=0 OR spent_index>=?) ",
            (puzzle_hash.hex(), height, height),
        )
        rows = await cursor.fetchall()

        await cursor.close()
        for row in rows:
            coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4], row[8]))
        return list(coins)
