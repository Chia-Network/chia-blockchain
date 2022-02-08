from typing import List, Optional, Set, Dict, Any, Tuple
from databases import Database
from sqlalchemy import bindparam
from sqlalchemy.sql import text
from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64
from chia.util.lru_cache import LRUCache
from chia.util import dialect_utils
from time import time
import logging

log = logging.getLogger(__name__)


class CoinStore:
    """
    This object handles CoinRecords in DB.
    A cache is maintained for quicker access to recent coins.
    """

    coin_record_db: Database
    coin_record_cache: LRUCache
    cache_size: uint32
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper, cache_size: uint32 = uint32(60000)):
        self = cls()

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper
        self.coin_record_db = db_wrapper.db

        async with self.coin_record_db.connection() as connection:
            async with connection.transaction():
                if self.db_wrapper.db_version == 2:

                    # the coin_name is unique in this table because the CoinStore always
                    # only represent a single peak
                    await self.coin_record_db.execute(
                        "CREATE TABLE IF NOT EXISTS coin_record("
                        f"coin_name {dialect_utils.data_type('blob', self.db_wrapper.db.url.dialect)} PRIMARY KEY,"
                        " confirmed_index bigint,"
                        " spent_index bigint,"  # if this is zero, it means the coin has not been spent
                        " coinbase int,"
                        f" puzzle_hash {dialect_utils.data_type('blob', self.db_wrapper.db.url.dialect)},"
                        f" coin_parent {dialect_utils.data_type('blob', self.db_wrapper.db.url.dialect)},"
                        f" amount {dialect_utils.data_type('blob', self.db_wrapper.db.url.dialect)},"  # we use a blob of 8 bytes to store uint64
                        " timestamp bigint)"
                    )

                else:

                    # the coin_name is unique in this table because the CoinStore always
                    # only represent a single peak
                    await self.coin_record_db.execute(
                        (
                            "CREATE TABLE IF NOT EXISTS coin_record("
                            f"coin_name {dialect_utils.data_type('text-as-index', self.coin_record_db.url.dialect)} PRIMARY KEY,"
                            " confirmed_index bigint,"
                            " spent_index bigint,"
                            " spent int,"
                            " coinbase int,"
                            f" puzzle_hash {dialect_utils.data_type('text-as-index', self.coin_record_db.url.dialect)},"
                            f" coin_parent {dialect_utils.data_type('text-as-index', self.coin_record_db.url.dialect)},"
                            f" amount {dialect_utils.data_type('blob', self.db_wrapper.db.url.dialect)},"
                            " timestamp bigint)"
                        )
                    )

                # Useful for reorg lookups
                await dialect_utils.create_index_if_not_exists(self.coin_record_db, 'coin_confirmed_index', 'coin_record', ['confirmed_index'])

                await dialect_utils.create_index_if_not_exists(self.coin_record_db, 'coin_spent_index', 'coin_record', ['spent_index'])

                await dialect_utils.create_index_if_not_exists(self.coin_record_db, 'coin_puzzle_hash', 'coin_record', ['puzzle_hash'])

                await dialect_utils.create_index_if_not_exists(self.coin_record_db, 'coin_parent_index', 'coin_record', ['coin_parent'])

        self.coin_record_cache = LRUCache(cache_size)
        return self

    async def num_unspent(self) -> int:
        row = await self.coin_record_db.fetch_one("SELECT COUNT(*) FROM coin_record WHERE spent_index=0")
        if row is not None:
            return row[0]
        return 0

    def maybe_from_hex(self, field: Any) -> bytes:
        if self.db_wrapper.db_version == 2:
            return field
        else:
            return bytes.fromhex(field)

    def maybe_to_hex(self, field: bytes) -> Any:
        if self.db_wrapper.db_version == 2:
            return field
        else:
            return field.hex()

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
                True,
                timestamp,
            )
            additions.append(reward_coin_r)

        async with self.coin_record_db.connection() as connection:
            async with connection.transaction():
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
        row = await self.coin_record_db.fetch_one(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            "coin_parent, amount, timestamp FROM coin_record WHERE coin_name= :coin_name",
            {"coin_name": self.maybe_to_hex(coin_name)}
        )
        if row is not None:
            coin = self.row_to_coin(row)
            record = CoinRecord(coin, row[0], row[1], row[2], row[6])
            self.coin_record_cache.put(record.coin.name(), record)
            return record
        return None

    async def get_coins_added_at_height(self, height: uint32) -> List[CoinRecord]:
        rows = await self.coin_record_db.fetch_all(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            "coin_parent, amount, timestamp FROM coin_record WHERE confirmed_index=:height",
            {"height": int(height)},
        )
        coins = []
        for row in rows:
            coin = self.row_to_coin(row)
            coins.append(CoinRecord(coin, row[0], row[1], row[2], row[6]))
        return coins

    async def get_coins_removed_at_height(self, height: uint32) -> List[CoinRecord]:
        # Special case to avoid querying all unspent coins (spent_index=0)
        if height == 0:
            return []
        rows = await self.coin_record_db.fetch_all(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            "coin_parent, amount, timestamp FROM coin_record WHERE spent_index=:height",
            {"height": int(height)},
        )
        coins = []
        for row in rows:
            if row[1] != 0:
                coin = self.row_to_coin(row)
                coin_record = CoinRecord(coin, row[0], row[1], row[2], row[6])
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

        rows = await self.coin_record_db.fetch_all(
            f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            f"coin_parent, amount, timestamp FROM coin_record {dialect_utils.indexed_by('coin_puzzle_hash', self.coin_record_db.url.dialect)} WHERE puzzle_hash=:puzzle_hash "
            f"AND confirmed_index>=:start_height AND confirmed_index<:end_height "
            f"{'' if include_spent_coins else 'AND spent_index=0'}",
            {"puzzle_hash": self.maybe_to_hex(puzzle_hash), "start_height": int(start_height), "end_height": int(end_height)},
        )

        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))
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
        puzzle_hashes_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            puzzle_hashes_db = tuple(puzzle_hashes)
        else:
            puzzle_hashes_db = tuple([ph.hex() for ph in puzzle_hashes])

        query = text(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            f"coin_parent, amount, timestamp FROM coin_record {dialect_utils.indexed_by('coin_puzzle_hash', self.coin_record_db.url.dialect)} "
            "WHERE confirmed_index>=:start_height AND confirmed_index<:end_height "
            'AND puzzle_hash in :puzzle_hashes_db '
            f"{'' if include_spent_coins else 'AND spent_index=0'}"
        )
        query = query.bindparams(
            bindparam("puzzle_hashes_db", puzzle_hashes_db, expanding=True),
            bindparam("start_height", int(start_height)),
            bindparam("end_height", int(end_height))
        )
        rows = await self.coin_record_db.fetch_all(query)

        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))
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
        names_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            names_db = tuple(names)
        else:
            names_db = tuple([name.hex() for name in names])

        query = text(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            'coin_parent, amount, timestamp FROM coin_record '
            "WHERE confirmed_index>=:start_height AND confirmed_index<:end_height "
            "AND coin_name in :coin_names "
            f"{'' if include_spent_coins else 'AND spent_index=0'}"
        )
        query = query.bindparams(
            bindparam("coin_names", names_db, expanding=True),
            bindparam("start_height", int(start_height)),
            bindparam("end_height", int(end_height))
        )
        rows = await self.coin_record_db.fetch_all(query)

        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))

        return list(coins)

    def row_to_coin(self, row) -> Coin:
        return Coin(
            bytes32(self.maybe_from_hex(row[4])), bytes32(self.maybe_from_hex(row[3])), uint64.from_bytes(row[5])
        )

    def row_to_coin_state(self, row):
        coin = self.row_to_coin(row)
        spent_h = None
        if row[1] != 0:
            spent_h = row[1]
        return CoinState(coin, spent_h, row[0])

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
        puzzle_hashes_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            puzzle_hashes_db = tuple(puzzle_hashes)
        else:
            puzzle_hashes_db = tuple([ph.hex() for ph in puzzle_hashes])

        query = text(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            f"coin_parent, amount, timestamp FROM coin_record {dialect_utils.indexed_by('coin_puzzle_hash', self.coin_record_db.url.dialect)} "
            "WHERE confirmed_index>=:start_height AND confirmed_index<:end_height "
            'AND puzzle_hash in :puzzle_hashes '
            f"{'' if include_spent_coins else 'AND spent_index=0'}",
        )
        query = query.bindparams(
            bindparam("puzzle_hashes", puzzle_hashes_db, expanding=True),
            bindparam("start_height", int(start_height)),
            bindparam("end_height", int(end_height))
        )
        rows = await self.coin_record_db.fetch_all(query)

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
        parent_ids_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            parent_ids_db = tuple(parent_ids)
        else:
            parent_ids_db = tuple([pid.hex() for pid in parent_ids])

        query = text(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            'coin_parent, amount, timestamp FROM coin_record '
            'WHERE confirmed_index>=:start_height AND confirmed_index<:end_height '
            "AND coin_parent in :coin_parent_ids "
            f"{'' if include_spent_coins else 'AND spent_index=0'}"
        )
        query = query.bindparams(
            bindparam("coin_parent_ids", parent_ids_db, expanding=True),
            bindparam("start_height", int(start_height)),
            bindparam("end_height", int(end_height))
        )
        rows = await self.coin_record_db.fetch_all(query)

        for row in rows:
            coin = self.row_to_coin(row)
            coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))
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
        coin_ids_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            coin_ids_db = tuple(coin_ids)
        else:
            coin_ids_db = tuple([pid.hex() for pid in coin_ids])
        query = text(
            f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            f'coin_parent, amount, timestamp FROM coin_record '
            f"WHERE confirmed_index>=:start_height AND confirmed_index<:end_height "
            "AND coin_name in :coin_names "
            f"{'' if include_spent_coins else 'AND spent_index=0'}",
        )
        query = query.bindparams(
            bindparam("coin_names", coin_ids_db, expanding=True),
            bindparam("start_height", int(start_height)),
            bindparam("end_height", int(end_height))
        )
        rows = await self.coin_record_db.fetch_all(query)

        for row in rows:
            coins.add(self.row_to_coin_state(row))
        return list(coins)

    async def rollback_to_block(self, block_index: int) -> List[CoinRecord]:
        """
        Note that block_index can be negative, in which case everything is rolled back
        Returns the list of coin records that have been modified
        """
        # Update memory cache
        delete_queue: List[bytes32] = []
        for coin_name, coin_record in list(self.coin_record_cache.cache.items()):
            if int(coin_record.spent_block_index) > block_index:
                new_record = CoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    uint32(0),
                    coin_record.coinbase,
                    coin_record.timestamp,
                )
                self.coin_record_cache.put(coin_record.coin.name(), new_record)
            if int(coin_record.confirmed_block_index) > block_index:
                delete_queue.append(coin_name)

        for coin_name in delete_queue:
            self.coin_record_cache.remove(coin_name)

        coin_changes: Dict[bytes32, CoinRecord] = {}
        rows = await self.coin_record_db.fetch_all(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            "coin_parent, amount, timestamp FROM coin_record WHERE confirmed_index>:min_confirmed_index",
            {"min_confirmed_index": int(block_index)},
        )
        for row in rows:
            coin = self.row_to_coin(row)
            record = CoinRecord(coin, uint32(0), row[1], row[2], uint64(0))
            coin_changes[record.name] = record

        # Delete from storage
        await self.coin_record_db.execute("DELETE FROM coin_record WHERE confirmed_index>:min_confirmed_index",  {"min_confirmed_index": int(block_index)})

        rows = await self.coin_record_db.fetch_all(
            "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
            "coin_parent, amount, timestamp FROM coin_record WHERE confirmed_index>:min_confirmed_index",
            {"min_confirmed_index": int(block_index)},
        )
        for row in rows:
            coin = self.row_to_coin(row)
            record = CoinRecord(coin, row[0], uint32(0), row[2], row[6])
            if record.name not in coin_changes:
                coin_changes[record.name] = record

        if self.db_wrapper.db_version == 2:
            await self.coin_record_db.execute(
                "UPDATE coin_record SET spent_index=0 WHERE spent_index>:min_spent_index", {"min_spent_index": int(block_index)}
            )
        else:
            await self.coin_record_db.execute(
                "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>:min_spent_index", {"min_spent_index": int(block_index)}
            )
        return list(coin_changes.values())

    # Store CoinRecord in DB and ram cache
    async def _add_coin_records(self, records: List[CoinRecord]) -> None:

        if self.db_wrapper.db_version == 2:
            values2 = []
            for record in records:
                self.coin_record_cache.put(record.coin.name(), record)
                values2.append(
                    {
                        "coin_name": record.coin.name(),
                        "confirmed_block_index": int(record.confirmed_block_index),
                        "spent_block_index": int(record.spent_block_index),
                        "coinbase": int(record.coinbase),
                        "puzzle_hash": record.coin.puzzle_hash,
                        "parent_coin_info": record.coin.parent_coin_info,
                        "amount": bytes(record.coin.amount),
                        "timestamp": int(record.timestamp),
                    }
                )
            await self.coin_record_db.execute_many(
                "INSERT INTO coin_record VALUES(:coin_name, :confirmed_block_index, :spent_block_index, :coinbase, :puzzle_hash, :parent_coin_info, :amount, :timestamp)",
                values2,
            )
        else:
            values = []
            for record in records:
                self.coin_record_cache.put(record.coin.name(), record)
                values.append(
                    {
                        "coin_name": record.coin.name().hex(),
                        "confirmed_block_index": int(record.confirmed_block_index),
                        "spent_block_index": int(record.spent_block_index),
                        "spent": int(record.spent),
                        "coinbase": int(record.coinbase),
                        "puzzle_hash": record.coin.puzzle_hash.hex(),
                        "parent_coin_info": record.coin.parent_coin_info.hex(),
                        "amount": bytes(record.coin.amount),
                        "timestamp": int(record.timestamp),
                    }
                )
            await self.coin_record_db.execute_many(
                "INSERT INTO coin_record VALUES(:coin_name, :confirmed_block_index, :spent_block_index, :spent, :coinbase, :puzzle_hash, :parent_coin_info, :amount, :timestamp)",
                values,
            )

    # Update coin_record to be spent in DB
    async def _set_spent(self, coin_names: List[bytes32], index: uint32):

        assert len(coin_names) == 0 or index > 0
        # if this coin is in the cache, mark it as spent in there
        updates = []
        for coin_name in coin_names:
            r = self.coin_record_cache.get(coin_name)
            if r is not None:
                self.coin_record_cache.put(
                    r.name, CoinRecord(r.coin, r.confirmed_block_index, index, r.coinbase, r.timestamp)
                )
            updates.append({"spent_index": int(index), "coin_name": self.maybe_to_hex(coin_name)})

        if self.db_wrapper.db_version == 2:
            await self.coin_record_db.execute_many(
                "UPDATE coin_record SET spent_index=:spent_index WHERE coin_name=:coin_name", updates
            )
        else:
            await self.coin_record_db.execute_many(
                "UPDATE coin_record SET spent=1,spent_index=:spent_index WHERE coin_name=:coin_name", updates
            )
