from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar, cast

import typing_extensions
from aiosqlite import Cursor
from chia_rs import CoinRecord, CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.coin_commitments import EMPTY_MERKLE_SET_ROOT, compute_coin_commitments_root
from chia.consensus.coin_store_protocol import CoinStoreProtocol, CoinStoreSnapshot
from chia.types.blockchain_format.coin import Coin
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2

if TYPE_CHECKING:
    from chia.full_node.block_store import BlockStore

log = logging.getLogger(__name__)


def row_to_coin(row: sqlite3.Row) -> Coin:
    return Coin(bytes32(row[4]), bytes32(row[3]), uint64.from_bytes(row[5]))


def row_to_coin_state(row: sqlite3.Row) -> CoinState:
    coin = row_to_coin(row)
    spent_h = None
    if row[1] > 0:
        spent_h = row[1]
    return CoinState(coin, spent_h, row[0])


@typing_extensions.final
@dataclasses.dataclass
class _CoinStoreSnapshot:
    """
    A read view over the read transaction held open by `CoinStore.snapshot()`.
    Only obtainable through that context manager.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[CoinStoreSnapshot] = cast("_CoinStoreSnapshot", None)

    _coin_store: CoinStore
    _peak: tuple[uint32, bytes32] | None

    def peak(self) -> tuple[uint32, bytes32] | None:
        return self._peak

    async def get_coin_records(self, coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        return await self._coin_store.get_coin_records(coin_ids)

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        return await self._coin_store.get_coins_added_at_height(height)

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        return await self._coin_store.get_coins_removed_at_height(height)


@typing_extensions.final
@dataclasses.dataclass
class CoinStore:
    """
    This object handles CoinRecords in DB.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[CoinStoreProtocol] = cast("CoinStore", None)

    db_wrapper: DBWrapper2
    # Needed by snapshot() to read the peak. The peak physically lives in
    # BlockStore's tables for now; reading it over the snapshot's read
    # transaction (same database, same connection) keeps it consistent with
    # the coin reads. Moving the peak into the coin store is a later step.
    block_store: BlockStore | None = None

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2, block_store: BlockStore | None = None) -> CoinStore:
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"CoinStore does not support database schema v{db_wrapper.db_version}")
        if block_store is not None:
            # snapshot() consistency relies on both stores reading through
            # the same database wrapper (and thus the same read transaction)
            assert block_store.db_wrapper is db_wrapper
        self = CoinStore(db_wrapper, block_store)

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

            # Partial index: only spent coins (spent_index > 0). Unspent coins use
            # spent_index 0 or -1 and are never looked up by this index; height-0
            # removals are rejected in get_coins_removed_at_height. SQLite only
            # uses a partial index when the query WHERE implies the index
            # predicate, so lookups must include `spent_index>0` explicitly.
            # Existing DBs that already have a full coin_spent_index keep it
            # (CREATE IF NOT EXISTS); rebuilding would be too expensive.
            log.info("DB: Creating index coin_spent_index")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index) WHERE spent_index>0"
            )

            log.info("DB: Creating index coin_puzzle_hash")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_puzzle_hash on coin_record(puzzle_hash)")

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
        took_too_long = end - start > 10

        message = (
            f"Height {height}: It took {end - start:0.2f}s to apply {len(tx_additions)} additions and "
            + f"{len(tx_removals)} removals to the coin store."
        )

        if took_too_long:
            level = logging.WARNING
            message += " Make sure blockchain database is on a fast drive"
        else:
            level = logging.DEBUG

        log.log(level, message)

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(self, coin_name: bytes32) -> CoinRecord | None:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record WHERE coin_name=?",
                (coin_name,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is not None:
                    coin = row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    return CoinRecord(coin, row[0], spent_index, row[2] != 0, row[6])
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
                    coin = row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    record = CoinRecord(coin, row[0], spent_index, row[2] != 0, row[6])
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
                    coin = row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.append(CoinRecord(coin, row[0], spent_index, row[2] != 0, row[6]))
                return coins

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        # Special case to avoid querying all unspent coins (spent_index=0)
        if height == 0:
            return []
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                # `spent_index>0` is required for SQLite to use the partial coin_spent_index.
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp FROM coin_record "
                "WHERE spent_index=? AND spent_index>0",
                (height,),
            ) as cursor:
                coins = []
                for row in await cursor.fetchall():
                    if row[1] > 0:
                        coin = row_to_coin(row)
                        coin_record = CoinRecord(coin, row[0], row[1], row[2] != 0, row[6])
                        coins.append(coin_record)
                return coins

    @asynccontextmanager
    async def snapshot(self) -> AsyncGenerator[_CoinStoreSnapshot, None]:
        """
        Acquire a consistent read view of the coin store.

        This holds a read transaction open for the duration of the scope, so
        all reads made through the snapshot observe the same database state:
        writes committed after acquisition become visible only after the
        scope exits. The peak is read inside the same transaction (which also
        pins the sqlite snapshot) and cached, so `peak()` is consistent with
        the coin reads by construction.

        Reads must be made from the task that acquired the snapshot: the
        underlying read connection is associated with the current asyncio
        task, and reads from other tasks would use a different connection
        outside this transaction.
        """
        if self.block_store is None:
            raise RuntimeError("CoinStore.snapshot() requires a block_store reference to read the peak")
        async with self.db_wrapper.reader():
            peak: tuple[uint32, bytes32] | None = None
            peak_row = await self.block_store.get_peak()
            if peak_row is not None:
                peak = (peak_row[1], peak_row[0])
            yield _CoinStoreSnapshot(self, peak)

    async def get_coin_commitments_root(self, height: uint32) -> bytes32:
        # spent_index is 0 for unspent coins, so height 0 can't be queried; it has no spends
        if height == 0:
            return EMPTY_MERKLE_SET_ROOT

        # one reader snapshot, so a concurrent peak change can't mix coin states between the two queries
        async with self.db_wrapper.reader() as conn:
            async with conn.execute(
                # `spent_index>0` is required for SQLite to use the partial coin_spent_index.
                "SELECT coin_name FROM coin_record INDEXED BY coin_spent_index WHERE spent_index=? AND spent_index>0",
                (height,),
            ) as cursor:
                spent_coin_ids = [bytes32(row[0]) for row in await cursor.fetchall()]

            async with conn.execute(
                # coinbase=0 excludes reward coins
                "SELECT puzzle_hash, coin_parent, amount FROM coin_record INDEXED BY coin_confirmed_index "
                "WHERE confirmed_index=? AND coinbase=0",
                (height,),
            ) as cursor:
                created_coins = [
                    Coin(bytes32(row[1]), bytes32(row[0]), uint64.from_bytes(row[2])) for row in await cursor.fetchall()
                ]

        return compute_coin_commitments_root(spent_coin_ids, created_coins)

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
                coin = row_to_coin(row)
                spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                record = CoinRecord(coin, uint32(0), spent_index, row[2] != 0, uint64(0))
                coin_name = bytes32(row[7])
                coin_changes[coin_name] = record

            # Delete reverted blocks from storage
            await conn.execute("DELETE FROM coin_record WHERE confirmed_index>?", (block_index,))

            # Add coins that are confirmed in the reverted blocks to the list of changed coins.
            # `spent_index>0` is required for SQLite to use the partial coin_spent_index
            # (and correctly excludes unspent sentinels 0 / -1 for negative block_index).
            rows = await conn.execute_fetchall(
                "SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                "coin_parent, amount, timestamp, coin_name FROM coin_record "
                "WHERE spent_index>? AND spent_index>0",
                (block_index,),
            )
            for row in rows:
                coin = row_to_coin(row)
                record = CoinRecord(coin, row[0], uint32(0), row[2] != 0, row[6])
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
                WHERE spent_index > ? AND spent_index > 0
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

    async def is_empty(self) -> bool:
        """
        Returns True if the coin store is empty, False otherwise.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT coin_name FROM coin_record LIMIT 1") as cursor:
                row = await cursor.fetchone()
                return row is None or len(row) == 0
