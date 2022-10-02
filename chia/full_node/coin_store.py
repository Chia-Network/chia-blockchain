from __future__ import annotations

import dataclasses
import sqlite3
from typing import List, Optional, Set, Dict, Any, Tuple, Union

import typing_extensions
from aiosqlite import Cursor

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.db_wrapper import DBWrapper2, SQLITE_MAX_VARIABLE_NUMBER
from chia.util.ints import uint32, uint64
from chia.util.chunks import chunks
import time
import logging

from chia.util.lru_cache import LRUCache

log = logging.getLogger(__name__)


@typing_extensions.final
@dataclasses.dataclass
class CoinStore:
    """
    This object handles CoinRecords in DB.
    """

    db_wrapper: DBWrapper2
    coins_added_at_height_cache: LRUCache[uint32, List[CoinRecord]]

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> CoinStore:
        self = CoinStore(db_wrapper, LRUCache(100))

        async with self.db_wrapper.writer_maybe_transaction() as conn:

            log.info("DB: Creating coin store tables and indexes.")
            if self.db_wrapper.db_version == 2:

                # the coin_name is unique in this table because the CoinStore always
                # only represent a single peak
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS coin_record("
                    "coin_name blob PRIMARY KEY,"
                    " confirmed_index bigint,"
                    " spent_index bigint,"  # if this is zero, it means the coin has not been spent
                    " coinbase int,"
                    " puzzle_hash blob,"
                    " coin_parent blob,"
                    " amount blob,"  # we use a blob of 8 bytes to store uint64
                    " timestamp bigint)"
                )

            else:

                # the coin_name is unique in this table because the CoinStore always
                # only represent a single peak
                await conn.execute(
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
            log.info("DB: Creating index coin_confirmed_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)")

            log.info("DB: Creating index coin_spent_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)")

            log.info("DB: Creating index coin_puzzle_hash")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_puzzle_hash on coin_record(puzzle_hash)")

            log.info("DB: Creating index coin_parent_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_parent_index on coin_record(coin_parent)")

        return self

    async def num_unspent(self) -> int:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT COUNT(*) FROM coin_record WHERE spent_index=0") as cursor:
                row = await cursor.fetchone()
        if row is not None:
            count: int = row[0]
            return count
        return 0

    def maybe_from_hex(self, field: Union[bytes, str]) -> bytes32:
        if self.db_wrapper.db_version == 2:
            assert isinstance(field, bytes)
            return bytes32(field)
        else:
            assert isinstance(field, str)
            return bytes32.fromhex(field)

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

        start = time.monotonic()

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

        await self._add_coin_records(additions)
        await self._set_spent(tx_removals, height)

        end = time.monotonic()
        log.log(
            logging.WARNING if end - start > 10 else logging.DEBUG,
            f"Height {height}: It took {end - start:0.2f}s to apply {len(tx_additions)} additions and "
            + f"{len(tx_removals)} removals to the coin store. Make sure "
            + "blockchain database is on a fast drive",
        )

        return additions

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record WHERE coin_name=?",
                (self.maybe_to_hex(coin_name),),
            ) as cursor:
                row = await cursor.fetchone()
                if row is not None:
                    coin = self.row_to_coin(row)
                    return CoinRecord(coin, row[0], row[1], row[2], row[6])
        return None

    async def get_coin_records(self, names: List[bytes32]) -> List[CoinRecord]:
        if len(names) == 0:
            return []

        coins: List[CoinRecord] = []

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursors: List[Cursor] = []
            for names_chunk in chunks(names, SQLITE_MAX_VARIABLE_NUMBER):
                names_db: Tuple[Any, ...]
                if self.db_wrapper.db_version == 2:
                    names_db = tuple(names_chunk)
                else:
                    names_db = tuple([n.hex() for n in names_chunk])
                cursors.append(
                    await conn.execute(
                        f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                        f"coin_parent, amount, timestamp FROM coin_record "
                        f'WHERE coin_name in ({",".join(["?"] * len(names_db))}) ',
                        names_db,
                    )
                )

            for cursor in cursors:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    record = CoinRecord(coin, row[0], row[1], row[2], row[6])
                    coins.append(record)

        return coins

    async def get_coins_added_at_height(self, height: uint32) -> List[CoinRecord]:
        coins_added: Optional[List[CoinRecord]] = self.coins_added_at_height_cache.get(height)
        if coins_added is not None:
            return coins_added

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record WHERE confirmed_index=?",
                (height,),
            ) as cursor:
                rows = await cursor.fetchall()
                coins = []
                for row in rows:
                    coin = self.row_to_coin(row)
                    coins.append(CoinRecord(coin, row[0], row[1], row[2], row[6]))
                self.coins_added_at_height_cache.put(height, coins)
                return coins

    async def get_coins_removed_at_height(self, height: uint32) -> List[CoinRecord]:
        # Special case to avoid querying all unspent coins (spent_index=0)
        if height == 0:
            return []
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record WHERE spent_index=?",
                (height,),
            ) as cursor:
                coins = []
                for row in await cursor.fetchall():
                    if row[1] != 0:
                        coin = self.row_to_coin(row)
                        coin_record = CoinRecord(coin, row[0], row[1], row[2], row[6])
                        coins.append(coin_record)
                return coins

    async def get_all_coins(self, include_spent_coins: bool) -> List[CoinRecord]:
        # WARNING: this should only be used for testing or in a simulation,
        # running it on a synced testnet or mainnet node will most likely result in an OOM error.
        coins = set()

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record "
                f"{'' if include_spent_coins else 'INDEXED BY coin_spent_index WHERE spent_index=0'}"
                f" ORDER BY confirmed_index"
            ) as cursor:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))
                return list(coins)

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self,
        include_spent_coins: bool,
        puzzle_hash: bytes32,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> List[CoinRecord]:

        coins = set()

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record INDEXED BY coin_puzzle_hash WHERE puzzle_hash=? "
                f"AND confirmed_index>=? AND confirmed_index<? "
                f"{'' if include_spent_coins else 'AND spent_index=0'}",
                (self.maybe_to_hex(puzzle_hash), start_height, end_height),
            ) as cursor:

                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))
                return list(coins)

    async def get_coin_records_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> List[CoinRecord]:
        if len(puzzle_hashes) == 0:
            return []

        coins = set()
        puzzle_hashes_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            puzzle_hashes_db = tuple(puzzle_hashes)
        else:
            puzzle_hashes_db = tuple([ph.hex() for ph in puzzle_hashes])

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record INDEXED BY coin_puzzle_hash "
                f'WHERE puzzle_hash in ({"?," * (len(puzzle_hashes) - 1)}?) '
                f"AND confirmed_index>=? AND confirmed_index<? "
                f"{'' if include_spent_coins else 'AND spent_index=0'}",
                puzzle_hashes_db + (start_height, end_height),
            ) as cursor:

                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))
                return list(coins)

    async def get_coin_records_by_names(
        self,
        include_spent_coins: bool,
        names: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> List[CoinRecord]:
        if len(names) == 0:
            return []

        coins = set()
        names_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            names_db = tuple(names)
        else:
            names_db = tuple([name.hex() for name in names])

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record INDEXED BY sqlite_autoindex_coin_record_1 "
                f'WHERE coin_name in ({"?," * (len(names) - 1)}?) '
                f"AND confirmed_index>=? AND confirmed_index<? "
                f"{'' if include_spent_coins else 'AND spent_index=0'}",
                names_db + (start_height, end_height),
            ) as cursor:

                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))

        return list(coins)

    def row_to_coin(self, row: sqlite3.Row) -> Coin:
        return Coin(self.maybe_from_hex(row[4]), self.maybe_from_hex(row[3]), uint64.from_bytes(row[5]))

    def row_to_coin_state(self, row: sqlite3.Row) -> CoinState:
        coin = self.row_to_coin(row)
        spent_h = None
        if row[1] != 0:
            spent_h = row[1]
        return CoinState(coin, spent_h, row[0])

    async def get_coin_states_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: List[bytes32],
        min_height: uint32 = uint32(0),
    ) -> List[CoinState]:
        if len(puzzle_hashes) == 0:
            return []

        coins = set()
        async with self.db_wrapper.reader_no_transaction() as conn:
            for puzzles in chunks(puzzle_hashes, SQLITE_MAX_VARIABLE_NUMBER):
                puzzle_hashes_db: Tuple[Any, ...]
                if self.db_wrapper.db_version == 2:
                    puzzle_hashes_db = tuple(puzzles)
                else:
                    puzzle_hashes_db = tuple([ph.hex() for ph in puzzles])
                async with conn.execute(
                    f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                    f"coin_parent, amount, timestamp FROM coin_record INDEXED BY coin_puzzle_hash "
                    f'WHERE puzzle_hash in ({"?," * (len(puzzles) - 1)}?) '
                    f"AND (confirmed_index>=? OR spent_index>=?)"
                    f"{'' if include_spent_coins else 'AND spent_index=0'}",
                    puzzle_hashes_db + (min_height, min_height),
                ) as cursor:
                    row: sqlite3.Row
                    async for row in cursor:
                        coins.add(self.row_to_coin_state(row))

        return list(coins)

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: List[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> List[CoinRecord]:
        if len(parent_ids) == 0:
            return []

        coins = set()
        async with self.db_wrapper.reader_no_transaction() as conn:
            for ids in chunks(parent_ids, SQLITE_MAX_VARIABLE_NUMBER):
                parent_ids_db: Tuple[Any, ...]
                if self.db_wrapper.db_version == 2:
                    parent_ids_db = tuple(ids)
                else:
                    parent_ids_db = tuple([pid.hex() for pid in ids])
                async with conn.execute(
                    f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                    f'coin_parent, amount, timestamp FROM coin_record WHERE coin_parent in ({"?," * (len(ids) - 1)}?) '
                    f"AND confirmed_index>=? AND confirmed_index<? "
                    f"{'' if include_spent_coins else 'AND spent_index=0'}",
                    parent_ids_db + (start_height, end_height),
                ) as cursor:

                    async for row in cursor:
                        coin = self.row_to_coin(row)
                        coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))

        return list(coins)

    async def get_coin_states_by_ids(
        self,
        include_spent_coins: bool,
        coin_ids: List[bytes32],
        min_height: uint32 = uint32(0),
    ) -> List[CoinState]:
        if len(coin_ids) == 0:
            return []

        coins = set()
        async with self.db_wrapper.reader_no_transaction() as conn:
            for ids in chunks(coin_ids, SQLITE_MAX_VARIABLE_NUMBER):
                coin_ids_db: Tuple[Any, ...]
                if self.db_wrapper.db_version == 2:
                    coin_ids_db = tuple(ids)
                else:
                    coin_ids_db = tuple([pid.hex() for pid in ids])
                async with conn.execute(
                    f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                    f'coin_parent, amount, timestamp FROM coin_record WHERE coin_name in ({"?," * (len(ids) - 1)}?) '
                    f"AND (confirmed_index>=? OR spent_index>=?)"
                    f"{'' if include_spent_coins else 'AND spent_index=0'}",
                    coin_ids_db + (min_height, min_height),
                ) as cursor:
                    async for row in cursor:
                        coins.add(self.row_to_coin_state(row))
        return list(coins)

    async def rollback_to_block(self, block_index: int) -> List[CoinRecord]:
        """
        Note that block_index can be negative, in which case everything is rolled back
        Returns the list of coin records that have been modified
        """

        coin_changes: Dict[bytes32, CoinRecord] = {}
        # Add coins that are confirmed in the reverted blocks to the list of updated coins.
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            async with conn.execute(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record WHERE confirmed_index>?",
                (block_index,),
            ) as cursor:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    record = CoinRecord(coin, uint32(0), row[1], row[2], uint64(0))
                    coin_changes[record.name] = record

            # Delete reverted blocks from storage
            await conn.execute("DELETE FROM coin_record WHERE confirmed_index>?", (block_index,))

            # Add coins that are confirmed in the reverted blocks to the list of changed coins.
            async with conn.execute(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record WHERE spent_index>?",
                (block_index,),
            ) as cursor:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    record = CoinRecord(coin, row[0], uint32(0), row[2], row[6])
                    if record.name not in coin_changes:
                        coin_changes[record.name] = record

            if self.db_wrapper.db_version == 2:
                await conn.execute("UPDATE coin_record SET spent_index=0 WHERE spent_index>?", (block_index,))
            else:
                await conn.execute(
                    "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>?", (block_index,)
                )
        self.coins_added_at_height_cache = LRUCache(self.coins_added_at_height_cache.capacity)
        return list(coin_changes.values())

    # Store CoinRecord in DB
    async def _add_coin_records(self, records: List[CoinRecord]) -> None:

        if self.db_wrapper.db_version == 2:
            values2 = []
            for record in records:
                values2.append(
                    (
                        record.coin.name(),
                        record.confirmed_block_index,
                        record.spent_block_index,
                        int(record.coinbase),
                        record.coin.puzzle_hash,
                        record.coin.parent_coin_info,
                        bytes(uint64(record.coin.amount)),
                        record.timestamp,
                    )
                )
            if len(values2) > 0:
                async with self.db_wrapper.writer_maybe_transaction() as conn:
                    await conn.executemany(
                        "INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        values2,
                    )
        else:
            values = []
            for record in records:
                values.append(
                    (
                        record.coin.name().hex(),
                        record.confirmed_block_index,
                        record.spent_block_index,
                        int(record.spent),
                        int(record.coinbase),
                        record.coin.puzzle_hash.hex(),
                        record.coin.parent_coin_info.hex(),
                        bytes(uint64(record.coin.amount)),
                        record.timestamp,
                    )
                )
            if len(values) > 0:
                async with self.db_wrapper.writer_maybe_transaction() as conn:
                    await conn.executemany(
                        "INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        values,
                    )

    # Update coin_record to be spent in DB
    async def _set_spent(self, coin_names: List[bytes32], index: uint32) -> None:

        assert len(coin_names) == 0 or index > 0

        if len(coin_names) == 0:
            return None

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            rows_updated: int = 0
            for coin_names_chunk in chunks(coin_names, SQLITE_MAX_VARIABLE_NUMBER):
                name_params = ",".join(["?"] * len(coin_names_chunk))
                if self.db_wrapper.db_version == 2:
                    ret: Cursor = await conn.execute(
                        f"UPDATE OR FAIL coin_record INDEXED BY sqlite_autoindex_coin_record_1 "
                        f"SET spent_index={index} "
                        f"WHERE spent_index=0 "
                        f"AND coin_name IN ({name_params})",
                        coin_names_chunk,
                    )
                else:
                    ret = await conn.execute(
                        f"UPDATE OR FAIL coin_record INDEXED BY sqlite_autoindex_coin_record_1 "
                        f"SET spent=1, spent_index={index} "
                        f"WHERE spent_index=0 "
                        f"AND coin_name IN ({name_params})",
                        [name.hex() for name in coin_names_chunk],
                    )
                rows_updated += ret.rowcount
            if rows_updated != len(coin_names):
                raise ValueError(
                    f"Invalid operation to set spent, total updates {rows_updated} expected {len(coin_names)}"
                )
