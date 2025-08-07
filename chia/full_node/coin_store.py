from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from collections.abc import Collection
from typing import Any, ClassVar, Optional

import typing_extensions
from aiosqlite import Cursor
from chia_rs import CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.mempool_item import UnspentLineageInfo
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2

log = logging.getLogger(__name__)


@typing_extensions.final
@dataclasses.dataclass
class CoinStore:
    """
    This object handles CoinRecords in DB.
    """

    db_wrapper: DBWrapper2
    # Fall back to the `coin_puzzle_hash` index if the ff unspent index
    # does not exist.
    _unspent_lineage_for_ph_idx: str = "coin_puzzle_hash"

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> CoinStore:
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"CoinStore does not support database schema v{db_wrapper.db_version}")
        self = CoinStore(db_wrapper)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            log.info("DB: Creating coin store tables and indexes.")
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

            # Useful for reorg lookups
            log.info("DB: Creating index coin_confirmed_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)")

            log.info("DB: Creating index coin_spent_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)")

            log.info("DB: Creating index coin_puzzle_hash")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_puzzle_hash on coin_record(puzzle_hash)")

            log.info("DB: Creating index coin_parent_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_parent_index on coin_record(coin_parent)")

            async with conn.execute("SELECT 1 FROM coin_record LIMIT 1") as cursor:
                is_new_db = await cursor.fetchone() is None
            if is_new_db:
                log.info("DB: Creating index coin_record_ph_ff_unspent_idx")
                # This partial index optimizes fast forward singleton latest
                # unspent queries. We're only adding it to new DBs to avoid
                # complex migrations that affect the huge coin records table.
                # The performance benefit outweighs the cost of this partial
                # index as it only includes rows where spent_index is -1.
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS coin_record_ph_ff_unspent_idx
                        ON coin_record(puzzle_hash, spent_index)
                        WHERE spent_index = -1
                    """
                )
            async with conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'coin_record_ph_ff_unspent_idx'"
            ) as cursor:
                has_ff_unspent_idx = await cursor.fetchone() is not None
            if has_ff_unspent_idx:
                self._unspent_lineage_for_ph_idx = "coin_record_ph_ff_unspent_idx"

        return self

    async def num_unspent(self) -> int:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT COUNT(*) FROM coin_record WHERE spent_index <= 0") as cursor:
                row = await cursor.fetchone()
        if row is not None:
            count: int = row[0]
            return count
        return 0

    async def new_block(
        self,
        height: uint32,
        timestamp: uint64,
        included_reward_coins: Collection[Coin],
        tx_additions: Collection[tuple[bytes32, Coin, bool]],
        tx_removals: list[bytes32],
    ) -> None:
        """
        Only called for blocks which are blocks (and thus have rewards and transactions)
        """

        start = time.monotonic()

        db_values_to_insert = []

        for coin_id, coin, same_as_parent in tx_additions:
            db_values_to_insert.append(
                (
                    coin_id,
                    # confirmed_index
                    height,
                    # spent_index
                    -1 if same_as_parent else 0,
                    # coinbase
                    0,
                    coin.puzzle_hash,
                    coin.parent_coin_info,
                    coin.amount.stream_to_bytes(),
                    timestamp,
                )
            )

        if height == 0:
            assert len(included_reward_coins) == 0
        else:
            assert len(included_reward_coins) >= 2

        for coin in included_reward_coins:
            db_values_to_insert.append(
                (
                    coin.name(),
                    # confirmed_index
                    height,
                    # spent_index
                    0,
                    # coinbase
                    1,
                    coin.puzzle_hash,
                    coin.parent_coin_info,
                    coin.amount.stream_to_bytes(),
                    timestamp,
                )
            )

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.executemany("INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)", db_values_to_insert)
        await self._set_spent(tx_removals, height)

        end = time.monotonic()
        log.log(
            logging.WARNING if end - start > 10 else logging.DEBUG,
            f"Height {height}: It took {end - start:0.2f}s to apply {len(tx_additions)} additions and "
            + f"{len(tx_removals)} removals to the coin store. Make sure "
            + "blockchain database is on a fast drive",
        )

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record WHERE coin_name=?",
                (coin_name,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is not None:
                    coin = self.row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    return CoinRecord(coin, row[0], spent_index, row[2], row[6])
        return None

    async def get_coin_records(self, names: Collection[bytes32]) -> list[CoinRecord]:
        if len(names) == 0:
            return []

        coins: list[CoinRecord] = []

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursors: list[Cursor] = []
            for batch in to_batches(names, SQLITE_MAX_VARIABLE_NUMBER):
                names_db: tuple[Any, ...] = tuple(batch.entries)
                cursors.append(
                    await conn.execute(
                        f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                        f"coin_parent, amount, timestamp FROM coin_record "
                        f"WHERE coin_name in ({','.join(['?'] * len(names_db))}) ",
                        names_db,
                    )
                )

            for cursor in cursors:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    record = CoinRecord(coin, row[0], spent_index, row[2], row[6])
                    coins.append(record)

        return coins

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
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
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.append(CoinRecord(coin, row[0], spent_index, row[2], row[6]))
                return coins

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
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
                    if row[1] > 0:
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
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        coins = set()

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record INDEXED BY coin_puzzle_hash WHERE puzzle_hash=? "
                f"AND confirmed_index>=? AND confirmed_index<? "
                f"{'' if include_spent_coins else 'AND spent_index <= 0'}",
                (puzzle_hash, start_height, end_height),
            ) as cursor:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.add(CoinRecord(coin, row[0], spent_index, row[2], row[6]))
                return list(coins)

    async def get_coin_records_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        if len(puzzle_hashes) == 0:
            return []

        coins = set()
        puzzle_hashes_db: tuple[Any, ...]
        puzzle_hashes_db = tuple(puzzle_hashes)

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record INDEXED BY coin_puzzle_hash "
                f"WHERE puzzle_hash in ({'?,' * (len(puzzle_hashes) - 1)}?) "
                f"AND confirmed_index>=? AND confirmed_index<? "
                f"{'' if include_spent_coins else 'AND spent_index <= 0'}",
                (*puzzle_hashes_db, start_height, end_height),
            ) as cursor:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.add(CoinRecord(coin, row[0], spent_index, row[2], row[6]))
                return list(coins)

    async def get_coin_records_by_names(
        self,
        include_spent_coins: bool,
        names: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        if len(names) == 0:
            return []

        coins = set()

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record INDEXED BY sqlite_autoindex_coin_record_1 "
                f"WHERE coin_name in ({'?,' * (len(names) - 1)}?) "
                f"AND confirmed_index>=? AND confirmed_index<? "
                f"{'' if include_spent_coins else 'AND spent_index <= 0'}",
                [*names, start_height, end_height],
            ) as cursor:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.add(CoinRecord(coin, row[0], spent_index, row[2], row[6]))

        return list(coins)

    def row_to_coin(self, row: sqlite3.Row) -> Coin:
        return Coin(bytes32(row[4]), bytes32(row[3]), uint64.from_bytes(row[5]))

    def row_to_coin_state(self, row: sqlite3.Row) -> CoinState:
        coin = self.row_to_coin(row)
        spent_h = None
        if row[1] > 0:
            spent_h = row[1]
        return CoinState(coin, spent_h, row[0])

    async def get_coin_states_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: set[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_items: int = 50000,
    ) -> set[CoinState]:
        if len(puzzle_hashes) == 0:
            return set()

        coins: set[CoinState] = set()
        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(puzzle_hashes, SQLITE_MAX_VARIABLE_NUMBER):
                puzzle_hashes_db: tuple[Any, ...] = tuple(batch.entries)
                async with conn.execute(
                    f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                    f"coin_parent, amount, timestamp FROM coin_record INDEXED BY coin_puzzle_hash "
                    f"WHERE puzzle_hash in ({'?,' * (len(batch.entries) - 1)}?) "
                    f"AND (confirmed_index>=? OR spent_index>=?)"
                    f"{'' if include_spent_coins else ' AND spent_index <= 0'}"
                    " LIMIT ?",
                    (*puzzle_hashes_db, min_height, min_height, max_items - len(coins)),
                ) as cursor:
                    row: sqlite3.Row
                    for row in await cursor.fetchall():
                        coins.add(self.row_to_coin_state(row))

                if len(coins) >= max_items:
                    break

        return coins

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        if len(parent_ids) == 0:
            return []

        coins = set()
        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(parent_ids, SQLITE_MAX_VARIABLE_NUMBER):
                parent_ids_db: tuple[Any, ...] = tuple(batch.entries)
                async with conn.execute(
                    f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp "
                    f"FROM coin_record WHERE coin_parent in ({'?,' * (len(batch.entries) - 1)}?) "
                    f"AND confirmed_index>=? AND confirmed_index<? "
                    f"{'' if include_spent_coins else 'AND spent_index <= 0'}",
                    (*parent_ids_db, start_height, end_height),
                ) as cursor:
                    async for row in cursor:
                        coin = self.row_to_coin(row)
                        spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                        coins.add(CoinRecord(coin, row[0], spent_index, row[2], row[6]))

        return list(coins)

    async def get_coin_states_by_ids(
        self,
        include_spent_coins: bool,
        coin_ids: Collection[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_height: uint32 = uint32.MAXIMUM,
        max_items: int = 50000,
    ) -> list[CoinState]:
        if len(coin_ids) == 0:
            return []

        coins: list[CoinState] = []
        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(coin_ids, SQLITE_MAX_VARIABLE_NUMBER):
                coin_ids_db: tuple[Any, ...] = tuple(batch.entries)

                max_height_sql = ""
                if max_height != uint32.MAXIMUM:
                    max_height_sql = f"AND confirmed_index<={max_height} AND spent_index<={max_height}"

                async with conn.execute(
                    f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp "
                    f"FROM coin_record WHERE coin_name in ({'?,' * (len(batch.entries) - 1)}?) "
                    f"AND (confirmed_index>=? OR spent_index>=?) {max_height_sql}"
                    f"{'' if include_spent_coins else 'AND spent_index <= 0'}"
                    " LIMIT ?",
                    (*coin_ids_db, min_height, min_height, max_items - len(coins)),
                ) as cursor:
                    for row in await cursor.fetchall():
                        coins.append(self.row_to_coin_state(row))
                if len(coins) >= max_items:
                    break

        return coins

    MAX_PUZZLE_HASH_BATCH_SIZE: ClassVar[int] = SQLITE_MAX_VARIABLE_NUMBER - 10

    async def batch_coin_states_by_puzzle_hashes(
        self,
        puzzle_hashes: list[bytes32],
        *,
        min_height: uint32 = uint32(0),
        include_spent: bool = True,
        include_unspent: bool = True,
        include_hinted: bool = True,
        min_amount: uint64 = uint64(0),
        max_items: int = 50000,
    ) -> tuple[list[CoinState], Optional[uint32]]:
        """
        Returns the coin states, as well as the next block height (or `None` if finished).
        You cannot exceed `CoinStore.MAX_PUZZLE_HASH_BATCH_SIZE` puzzle hashes in the query.
        """

        # This should be able to be changed later without breaking the protocol.
        # We have a small deduction for other variables to be added to the query.
        assert len(puzzle_hashes) <= CoinStore.MAX_PUZZLE_HASH_BATCH_SIZE

        if len(puzzle_hashes) == 0:
            return [], None

        # Coin states are keyed by coin id to filter out and prevent duplicates.
        coin_states_dict: dict[bytes32, CoinState] = dict()
        coin_states: list[CoinState]

        async with self.db_wrapper.reader() as conn:
            puzzle_hashes_db = tuple(puzzle_hashes)
            puzzle_hash_count = len(puzzle_hashes_db)

            require_spent = "spent_index>0"
            require_unspent = "spent_index <= 0"
            amount_filter = "AND amount>=? " if min_amount > 0 else ""

            if include_spent and include_unspent:
                height_filter = ""
            elif include_spent:
                height_filter = f"AND {require_spent}"
            elif include_unspent:
                height_filter = f"AND {require_unspent}"
            else:
                # There are no coins which are both spent and unspent, so we're finished.
                return [], None

            cursor = await conn.execute(
                f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                f"coin_parent, amount, timestamp FROM coin_record INDEXED BY coin_puzzle_hash "
                f"WHERE puzzle_hash in ({'?,' * (puzzle_hash_count - 1)}?) "
                f"AND (confirmed_index>=? OR spent_index>=?) "
                f"{height_filter} {amount_filter}"
                f"ORDER BY MAX(confirmed_index, spent_index) ASC "
                f"LIMIT ?",
                (
                    puzzle_hashes_db
                    + (min_height, min_height)
                    + ((min_amount.to_bytes(8, "big"),) if min_amount > 0 else ())
                    + (max_items + 1,)
                ),
            )

            for row in await cursor.fetchall():
                coin_state = self.row_to_coin_state(row)
                coin_states_dict[coin_state.coin.name()] = coin_state

            if include_hinted:
                cursor = await conn.execute(
                    f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                    f"coin_parent, amount, timestamp FROM coin_record INDEXED BY sqlite_autoindex_coin_record_1 "
                    f"WHERE coin_name IN (SELECT coin_id FROM hints "
                    f"WHERE hint IN ({'?,' * (puzzle_hash_count - 1)}?)) "
                    f"AND (confirmed_index>=? OR spent_index>=?) "
                    f"{height_filter} {amount_filter}"
                    f"ORDER BY MAX(confirmed_index, spent_index) ASC "
                    f"LIMIT ?",
                    (
                        puzzle_hashes_db
                        + (min_height, min_height)
                        + ((min_amount.to_bytes(8, "big"),) if min_amount > 0 else ())
                        + (max_items + 1,)
                    ),
                )

                for row in await cursor.fetchall():
                    coin_state = self.row_to_coin_state(row)
                    coin_states_dict[coin_state.coin.name()] = coin_state

            coin_states = list(coin_states_dict.values())

            if include_hinted:
                coin_states.sort(key=lambda cr: max(cr.created_height or uint32(0), cr.spent_height or uint32(0)))
                while len(coin_states) > max_items + 1:
                    coin_states.pop()

        # If there aren't too many coin states, we've finished syncing these hashes.
        # There is no next height to start from, so return `None`.
        if len(coin_states) <= max_items:
            return coin_states, None

        # The last item is the start of the next batch of coin states.
        next_coin_state = coin_states.pop()
        next_height = uint32(max(next_coin_state.created_height or 0, next_coin_state.spent_height or 0))

        # In order to prevent blocks from being split up between batches, remove
        # all coin states whose max height is the same as the last coin state's height.
        while len(coin_states) > 0:
            last_coin_state = coin_states[-1]
            height = uint32(max(last_coin_state.created_height or 0, last_coin_state.spent_height or 0))
            if height != next_height:
                break

            coin_states.pop()

        return coin_states, next_height

    async def rollback_to_block(self, block_index: int) -> dict[bytes32, CoinRecord]:
        """
        Note that block_index can be negative, in which case everything is rolled back
        Returns a map of coin ID to coin record for modified items.
        """

        coin_changes: dict[bytes32, CoinRecord] = {}
        # Add coins that are confirmed in the reverted blocks to the list of updated coins.
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp, coin_name FROM coin_record WHERE confirmed_index>?",
                (block_index,),
            )
            for row in rows:
                coin = self.row_to_coin(row)
                spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                record = CoinRecord(coin, uint32(0), spent_index, row[2], uint64(0))
                coin_name = bytes32(row[7])
                coin_changes[coin_name] = record

            # Delete reverted blocks from storage
            await conn.execute("DELETE FROM coin_record WHERE confirmed_index>?", (block_index,))

            # Add coins that are confirmed in the reverted blocks to the list of changed coins.
            rows = await conn.execute_fetchall(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp, coin_name FROM coin_record WHERE spent_index>?",
                (block_index,),
            )
            for row in rows:
                coin = self.row_to_coin(row)
                record = CoinRecord(coin, row[0], uint32(0), row[2], row[6])
                coin_name = bytes32(row[7])
                if coin_name not in coin_changes:
                    coin_changes[coin_name] = record

            # If the coin to update is not a reward coin and its parent is
            # spent and has the same puzzle hash and amount, we set its
            # spent_index to -1 as a potential fast forward singleton unspent
            # otherwise we set it to 0 as a normal unspent.
            await conn.execute(
                """
                UPDATE coin_record INDEXED BY coin_spent_index
                SET spent_index = CASE
                    WHEN
                        coinbase = 0 AND
                        EXISTS (
                            SELECT 1
                            FROM coin_record AS parent INDEXED BY sqlite_autoindex_coin_record_1
                            WHERE
                                parent.coin_name = coin_record.coin_parent AND
                                parent.puzzle_hash = coin_record.puzzle_hash AND
                                parent.amount = coin_record.amount AND
                                parent.spent_index > 0
                        )
                    THEN -1
                    ELSE 0
                END
                WHERE spent_index > ?
                """,
                (block_index,),
            )
        return coin_changes

    # Update coin_record to be spent in DB
    async def _set_spent(self, coin_names: list[bytes32], index: uint32) -> None:
        assert len(coin_names) == 0 or index > 0

        if len(coin_names) == 0:
            return None

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            rows_updated: int = 0
            for batch in to_batches(coin_names, SQLITE_MAX_VARIABLE_NUMBER):
                name_params = ",".join(["?"] * len(batch.entries))
                ret: Cursor = await conn.execute(
                    f"UPDATE coin_record INDEXED BY sqlite_autoindex_coin_record_1 "
                    f"SET spent_index={index} "
                    f"WHERE spent_index <= 0 "
                    f"AND coin_name IN ({name_params})",
                    batch.entries,
                )
                rows_updated += ret.rowcount
            if rows_updated != len(coin_names):
                raise ValueError(
                    f"Invalid operation to set spent, total updates {rows_updated} expected {len(coin_names)}"
                )

    # Lookup the most recent unspent lineage that matches a puzzle hash
    async def get_unspent_lineage_info_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[UnspentLineageInfo]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT unspent.coin_name, "
                "unspent.coin_parent, "
                "parent.coin_parent "
                "FROM coin_record AS unspent "
                f"INDEXED BY {self._unspent_lineage_for_ph_idx} "
                "LEFT JOIN coin_record AS parent ON unspent.coin_parent = parent.coin_name "
                "WHERE unspent.spent_index = -1 "
                "AND parent.spent_index > 0 "
                "AND unspent.puzzle_hash = ? "
                "AND parent.puzzle_hash = unspent.puzzle_hash "
                "AND parent.amount = unspent.amount",
                (puzzle_hash,),
            ) as cursor:
                rows = list(await cursor.fetchall())
                if len(rows) != 1:
                    log.debug("Expected 1 unspent with puzzle hash %s, but found %s", puzzle_hash.hex(), len(rows))
                    return None
                coin_id, parent_id, parent_parent_id = rows[0]
                return UnspentLineageInfo(
                    coin_id=bytes32(coin_id), parent_id=bytes32(parent_id), parent_parent_id=bytes32(parent_parent_id)
                )

    async def is_empty(self) -> bool:
        """
        Returns True if the coin store is empty, False otherwise.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT coin_name FROM coin_record LIMIT 1") as cursor:
                row = await cursor.fetchone()
                return row is None or len(row) == 0
