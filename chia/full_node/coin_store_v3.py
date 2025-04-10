from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from collections.abc import Collection
from typing import Any, Optional

import typing_extensions
from aiosqlite import Cursor
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from rocks_pyo3 import DB

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.eligible_coin_spends import UnspentLineageInfo
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2

log = logging.getLogger(__name__)


def index_to_blob(index: int) -> bytes:
    return index.to_bytes(8, "big")


def blob_to_index(blob: bytes) -> int:
    return int.from_bytes(blob, "big")


@typing_extensions.final
@dataclasses.dataclass
class CoinStore:
    """
    This object handles CoinRecords in DB.
    """

    db_wrapper: DBWrapper2
    rocks_db: DB

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> CoinStore:
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"CoinStore does not support database schema v{db_wrapper.db_version}")
        self = CoinStore(db_wrapper, db_wrapper.rocks_db())

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            log.info("DB: Creating coin store tables and indexes.")
            # the coin_name is unique in this table because the CoinStore always
            # only represent a single peak
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS coin_record("
                " confirmed_index bigint,"
                " spent_index bigint,"  # if this is zero, it means the coin has not been spent
                " coinbase int,"
                " puzzle_hash blob,"
                " coin_parent blob,"
                " amount blob,"  # we use a blob of 8 bytes to store uint64
                " timestamp bigint)"
            )

        return self

    async def any_coins_unspent(self) -> bool:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT * FROM coin_record WHERE spent_index=0") as cursor:
                _row = await cursor.fetchone()
                return True
        return False

    async def new_block(
        self,
        height: uint32,
        timestamp: uint64,
        included_reward_coins: Collection[Coin],
        tx_additions: Collection[Coin],
        tx_removals: list[bytes32],
    ) -> list[CoinRecord]:
        """
        Only called for blocks which have coins (and thus have rewards and transactions)
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
        r = await self.get_coin_records([coin_name])
        if len(r) == 0:
            return None
        return r[0]

    async def get_coin_records(self, names: Collection[bytes32]) -> list[CoinRecord]:
        if len(names) == 0:
            return []

        index_list = await self.coin_indices_for_names(names)

        return await self.coin_records_for_indices(index_list)

    async def coin_records_for_indices(self, indices: Collection[uint32]) -> list[CoinRecord]:
        coins = []
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursors: list[Cursor] = []
            for batch in to_batches(indices, SQLITE_MAX_VARIABLE_NUMBER):
                names_db: tuple[Any, ...] = tuple(batch.entries)
                cursors.append(
                    await conn.execute(
                        f"SELECT confirmed_index, spent_index, coinbase, puzzle_hash, "
                        f"coin_parent, amount, timestamp FROM coin_record "
                        f"WHERE rowid in ({','.join(['?'] * len(names_db))}) ",
                        names_db,
                    )
                )

            for cursor in cursors:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    record = CoinRecord(coin, row[0], row[1], row[2], row[6])
                    coins.append(record)

        return coins

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        # TODO:
        # add a table to store creations/spends at each height
        coins_added: Optional[list[CoinRecord]] = self.coins_added_at_height_cache.get(height)
        if coins_added is not None:
            return coins_added

        index_list = self.coin_indices_created_at_height(height)
        coins = await self.get_coin_records_by_indices(index_list)
        self.coins_added_at_height_cache.put(height, coins)
        return coins

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        # TODO:
        # add a table to store creations/spends at each height
        # Special case to avoid querying all unspent coins (spent_index=0)
        if height == 0:
            return []
        index_list = self.coin_indices_spent_at_height(height)
        return await self.get_coin_records_by_indices(index_list)

    async def get_all_coins(self, include_spent_coins: bool) -> list[CoinRecord]:
        raise NotImplementedError("get_all_coins is deprecated")

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self,
        include_spent_coins: bool,
        puzzle_hash: bytes32,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        return await self.get_coin_records_by_puzzle_hashes(
            include_spent_coins, [puzzle_hash], start_height, end_height
        )

    async def get_coin_records_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        # TODO: figure out how this will be implemented
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
                f"{'' if include_spent_coins else 'AND spent_index=0'}",
                (*puzzle_hashes_db, start_height, end_height),
            ) as cursor:
                for row in await cursor.fetchall():
                    coin = self.row_to_coin(row)
                    coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))
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

        index_list = await self.coin_indices_for_names(names)
        coins = await self.get_coin_records_by_indices(index_list)
        coins = [coin for coin in coins if start_height <= coin.confirmed_block_index < end_height]
        return coins

    def row_to_coin(self, row: sqlite3.Row) -> Coin:
        return Coin(bytes32(row[4]), bytes32(row[3]), uint64.from_bytes(row[5]))

    def row_to_coin_state(self, row: sqlite3.Row) -> CoinState:
        coin = self.row_to_coin(row)
        spent_h = None
        if row[1] != 0:
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
        # TODO: figure out how this will be implemented
        raise NotImplementedError("get_coin_states_by_puzzle_hashes is deprecated")
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
                    f"{'' if include_spent_coins else 'AND spent_index=0'}"
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
        # TODO: figure out how this will be implemented
        raise NotImplementedError("get_coin_records_by_parent_ids is deprecated")
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
                    f"{'' if include_spent_coins else 'AND spent_index=0'}",
                    (*parent_ids_db, start_height, end_height),
                ) as cursor:
                    async for row in cursor:
                        coin = self.row_to_coin(row)
                        coins.add(CoinRecord(coin, row[0], row[1], row[2], row[6]))

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
        raise NotImplementedError("get_coin_states_by_ids is not implemented")
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
                    f"{'' if include_spent_coins else 'AND spent_index=0'}"
                    " LIMIT ?",
                    (*coin_ids_db, min_height, min_height, max_items - len(coins)),
                ) as cursor:
                    for row in await cursor.fetchall():
                        coins.append(self.row_to_coin_state(row))
                if len(coins) >= max_items:
                    break

        return coins

    MAX_PUZZLE_HASH_BATCH_SIZE = SQLITE_MAX_VARIABLE_NUMBER - 10

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
        raise NotImplementedError("batch_coin_states_by_puzzle_hashes is not implemented")
        # TODO: create a rocksdb entry by puzzle hash with puzzle_hash/confirmed_block as the key

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
            require_unspent = "spent_index=0"
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

    async def rollback_to_block(self, block_index: int) -> list[CoinRecord]:
        """
        Note that block_index can be negative, in which case everything is rolled back
        Returns the list of coin records that have been modified
        """
        # TODO: get list of coins that were added and spent at this height
        # - get list of all blocks with index >= block_index
        # - get list of all coins with confirmed_index >= block_index
        raise NotImplementedError("rollback_to_block is not implemented")
        coin_delete_index_list = self.coin_indices_created_at_height(uint32(block_index))
        coin_spent_index_list = self.coin_indices_spent_at_height(uint32(block_index))

        coin_changes: dict[bytes32, CoinRecord] = {}
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

            await conn.execute("UPDATE coin_record SET spent_index=0 WHERE spent_index>?", (block_index,))
        return list(coin_changes.values())

    # Store CoinRecord in DB
    async def _add_coin_records(self, records: list[CoinRecord]) -> None:
        name_index_list: list[tuple[bytes32, int]] = []
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            for record in records:
                cursor = await conn.execute(
                    "INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.confirmed_block_index,
                        record.spent_block_index,
                        int(record.coinbase),
                        record.coin.puzzle_hash,
                        record.coin.parent_coin_info,
                        uint64(record.coin.amount).stream_to_bytes(),
                        record.timestamp,
                    ),
                )
                rowid = cursor.lastrowid
                assert rowid is not None
                name = record.coin.name()
                name_index_list.append((name, rowid))
            for name, index in name_index_list:
                index_blob = index_to_blob(index)
                self.rocks_db.put(name, index_blob)

    # Update coin_record to be spent in DB
    async def _set_spent(self, coin_names: list[bytes32], index: uint32) -> None:
        assert len(coin_names) == 0 or index > 0

        if len(coin_names) == 0:
            return None

        index_list = await self.coin_indices_for_names(coin_names)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            rows_updated: int = 0
            for batch in to_batches(index_list, SQLITE_MAX_VARIABLE_NUMBER):
                name_params = ",".join(["?"] * len(batch.entries))
                ret: Cursor = await conn.execute(
                    f"UPDATE coin_record "
                    f"SET spent_index={index} "
                    f"WHERE spent_index=0 "
                    f"AND rowid IN ({name_params})",
                    batch.entries,
                )
                rows_updated += ret.rowcount
            if rows_updated != len(coin_names):
                raise ValueError(
                    f"Invalid operation to set spent, total updates {rows_updated} expected {len(coin_names)}"
                )

    # Lookup the most recent unspent lineage that matches a puzzle hash
    async def get_unspent_lineage_info_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[UnspentLineageInfo]:
        raise NotImplementedError("get_unspent_lineage_info_for_puzzle_hash is not implemented")
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT unspent.coin_name, "
                "unspent.coin_parent, "
                "parent.coin_parent "
                "FROM coin_record AS unspent INDEXED BY coin_puzzle_hash "
                "LEFT JOIN coin_record AS parent ON unspent.coin_parent = parent.coin_name "
                "WHERE unspent.spent_index = 0 "
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

    async def coin_indices_for_names(self, names: Collection[bytes32]) -> list[uint32]:
        r = self.rocks_db.multi_get(names)
        uint32_list = [int.from_bytes(_) for _ in r]
        return uint32_list
