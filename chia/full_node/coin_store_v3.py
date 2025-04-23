from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from collections.abc import AsyncGenerator, Collection
from typing import Any, Optional

import typing_extensions
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from rocks_pyo3 import DB, WriteBatch

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.eligible_coin_spends import UnspentLineageInfo
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER

log = logging.getLogger(__name__)


def u16_to_blob(index: int) -> bytes:
    return index.to_bytes(2, "big")


def u32_to_blob(index: int) -> bytes:
    return index.to_bytes(4, "big")


def u64_to_blob(index: int) -> bytes:
    return index.to_bytes(8, "big")


def blob_to_int(blob: bytes) -> int:
    return int.from_bytes(blob, "big")


def list_bytes32_to_blob(bs: list[bytes32]) -> bytes:
    size_blob = u16_to_blob(len(bs))
    return size_blob + b"".join(_ for _ in bs)


@dataclasses.dataclass
class BlockInfo:
    timestamp: uint64
    created_coins: list[bytes32]
    spent_coins: list[bytes32]

    def __bytes__(self) -> bytes:
        return (
            u64_to_blob(self.timestamp)
            + list_bytes32_to_blob(self.created_coins)
            + list_bytes32_to_blob(self.spent_coins)
        )

    @classmethod
    def from_bytes(cls, blob: bytes) -> BlockInfo:
        timestamp = uint64.from_bytes(blob[:8])
        size = blob_to_int(blob[8:10])
        offset = 10
        created_coins = []
        for _ in range(size):
            created_coins.append(bytes32(blob[offset : offset + 32]))
            offset += 32
        size = blob_to_int(blob[offset : offset + 2])
        offset += 2
        spent_coins = []
        for _ in range(size):
            spent_coins.append(bytes32(blob[offset : offset + 32]))
            offset += 32
        assert offset == len(blob)
        return BlockInfo(timestamp, created_coins, spent_coins)


@typing_extensions.final
@dataclasses.dataclass
class CoinStore:
    """
    This object handles CoinRecords in DB.
    """

    rocks_db: DB
    # schema:
    # c(32 bytes hash) => coin record
    # b(8 byte index) => block info

    @classmethod
    async def create(cls, rocks_db: DB) -> CoinStore:
        return CoinStore(rocks_db)

    async def any_coins_unspent(self) -> bool:
        raise NotImplementedError()

    async def num_unspent(self) -> int:
        # this seems useless and should probably be removed
        count = 0
        for key, value in self.rocks_db.iterate_from(b"c", "forward"):
            if key[:1] != b"c":
                break
            coin_record_blob = value
            coin_record = CoinRecord.from_bytes(coin_record_blob)
            if coin_record.confirmed_block_index > 0 and coin_record.spent_block_index == 0:
                count += 1
        return count

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

        new_coin_records = {}
        new_coin_names = []
        for coin_list, is_coinbase in [(included_reward_coins, True), (tx_additions, False)]:
            for coin in coin_list:
                coin_name = coin.name()
                new_coin_names.append(coin_name)
                record: CoinRecord = CoinRecord(
                    coin,
                    height,
                    uint32(0),
                    is_coinbase,
                    timestamp,
                )
                new_coin_records[coin_name] = record

        block_info = BlockInfo(timestamp, new_coin_names, tx_removals)

        if height == 0:
            assert len(included_reward_coins) == 0
        else:
            assert len(included_reward_coins) >= 2

        batch = WriteBatch()
        height_blob = u32_to_blob(height)
        block_key = b"b" + height_blob
        block_info_blob = bytes(block_info)
        batch.put(block_key, block_info_blob)

        new_spent_coin_records = []
        spent_coin_records = await self.get_coin_records(tx_removals)
        for cr, name in zip(spent_coin_records, tx_removals):
            if cr is None:
                cr = new_coin_records[name]
                if cr is None:
                    raise ValueError(f"can't find coin for {name.hex()}")
                cr = dataclasses.replace(cr, spent_block_index=height)
                new_coin_records[name] = cr
            else:
                cr = dataclasses.replace(cr, spent_block_index=height)
                new_spent_coin_records.append((name, cr))

        updated_coin_records = []

        for name, cr in new_coin_records.items():
            coin_record_blob = bytes(cr)
            index = b"c" + name
            batch.put(index, coin_record_blob)
            updated_coin_records.append(cr)

        for name, cr in new_spent_coin_records:
            coin_record_blob = bytes(cr)
            index = b"c" + name
            batch.put(index, coin_record_blob)
            updated_coin_records.append(cr)

        self.rocks_db.write(batch)

        end = time.monotonic()
        log.log(
            logging.WARNING if end - start > 10 else logging.DEBUG,
            f"Height {height}: It took {end - start:0.2f}s to apply {len(tx_additions)} additions and "
            + f"{len(tx_removals)} removals to the coin store. Make sure "
            + "blockchain database is on a fast drive",
        )

        return updated_coin_records

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        r = await self.get_coin_records([coin_name])
        if len(r) == 0:
            return None
        return r[0]

    async def get_coin_records(self, names: Collection[bytes32]) -> list[CoinRecord]:
        if len(names) == 0:
            return []

        def index_for_coin_name(name: bytes32) -> bytes:
            return b"c" + name

        indices = [index_for_coin_name(_) for _ in (names)]
        blobs = self.rocks_db.multi_get(indices)
        coin_records = [CoinRecord.from_bytes(_) if _ is not None else None for _ in blobs]
        return coin_records

    async def block_infos_for_heights(self, heights: list[int]) -> list[Optional[BlockInfo]]:
        def index_for_height(h: uint64) -> bytes:
            return b"b" + h.to_bytes(8, "big")

        indices = [index_for_height(_) for _ in heights]
        blobs = self.rocksdb.multi_get(indices)
        size_of_block_info = 32
        block_records = [BlockInfo.from_bytes(_) for _ in blobs[0::size_of_block_info]]
        return block_records

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
        keys = [b"c" + name for name in names]
        values = self.rocks_db.multi_get(keys)
        coin_records = []
        for name, value in zip(names, values):
            if value is None:
                raise ValueError(f"coin {name.hex()} not found in DB")
            coin_record = CoinRecord.from_bytes(value)
            # not sure what to do with heights
            if include_spent_coins or coin_record.spent_block_index == 0:
                coin_records.append(coin_record)
        return coin_records

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

    async def _coin_activity_after_height(self, block_index: int) -> AsyncGenerator[tuple[int, BlockInfo]]:
        """
        Yield tuples of (additions, removals) after the given block index in
        reverse chronological order (so largest block index first).
        """
        last_block_index = bytes.fromhex("62ffffffffffffffff")
        iterator = self.rocks_db.iterate_from(last_block_index, "reverse")
        for k, v in iterator:
            index = blob_to_int(k[1:])
            bi = BlockInfo.from_bytes(v)
            yield index, bi

    async def rollback_to_block(self, block_index: int) -> list[CoinRecord]:
        """
        Note that block_index can be negative, in which case everything is rolled back
        Returns the list of coin records that have been modified
        """
        coin_changes = {}
        async for index, block_info in self._coin_activity_after_height(block_index):
            if index <= block_index:
                break
            additions = block_info.created_coins
            removals = block_info.spent_coins
            names = set(additions + removals)
            coin_records = await self.get_coin_records_by_names(True, list(names))

            cr_by_name = {_.name: _ for _ in coin_records}
            batch = WriteBatch()
            for coin_name in removals:
                coin_record = cr_by_name.get(coin_name)
                assert coin_record is not None
                coin_record = dataclasses.replace(coin_record, spent_block_index=0)
                coin_record_blob = bytes(coin_record)
                key = b"c" + coin_name
                batch.put(key, coin_record_blob)
                coin_changes[coin_name] = coin_record
            for coin_name in additions:
                key = b"c" + coin_name
                batch.delete(key)
            self.rocks_db.write(batch)

        return list(coin_changes.values())

    async def _add_block_summary(
        self, height: uint32, timestamp: uint64, additions: list[Coin], removals: list[bytes32]
    ) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Convert additions and removals to blobs
            additions_blob = b"".join([coin.name for coin in additions])
            removals_blob = b"".join(removals)

            await conn.execute(
                "INSERT OR REPLACE INTO block_summary VALUES(?, ?, ?, ?)",
                (height, timestamp, additions_blob, removals_blob),
            )

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

        new_spent_coin_records = []
        spent_coin_records = await self.get_coin_records(coin_names)
        for cr, name in zip(spent_coin_records, coin_names):
            if cr is None:
                raise ValueError(f"can't find coin for {name.hex()}")
            if cr.spent_block_index != 0:
                raise ValueError("Invalid operation to set spent")
            cr = dataclasses.replace(cr, spent_block_index=index)
            new_spent_coin_records.append((name, cr))

        batch = WriteBatch()
        for name, cr in new_spent_coin_records:
            coin_record_blob = bytes(cr)
            index = b"c" + name
            batch.put(index, coin_record_blob)

        self.rocks_db.write(batch)

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
