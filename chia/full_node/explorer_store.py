from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Collection
from typing import TYPE_CHECKING, Any, ClassVar, cast

import typing_extensions
from chia_rs import CoinRecord, CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.full_node.coin_store import row_to_coin, row_to_coin_state
from chia.full_node.explorer_store_protocol import ExplorerStoreProtocol
from chia.types.mempool_item import UnspentLineageInfo
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2

log = logging.getLogger(__name__)


@typing_extensions.final
@dataclasses.dataclass
class ExplorerStore:
    """
    SQLite implementation of the explorer queries: coins by puzzle hash and
    parent, coin states, singleton lineage, and hints. It shares the
    database with the SQLite CoinStore and reads its `coin_record` table,
    whose indexes CoinStore creates.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ExplorerStoreProtocol] = cast("ExplorerStore", None)

    db_wrapper: DBWrapper2
    # Fall back to the `coin_puzzle_hash` index if the ff unspent index
    # does not exist.
    _unspent_lineage_for_ph_idx: str = "coin_puzzle_hash"
    _has_coin_parent_index: bool = False

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> ExplorerStore:
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"ExplorerStore does not support database schema v{db_wrapper.db_version}")

        self = ExplorerStore(db_wrapper)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            log.info("DB: Creating hint store tables and indexes.")
            await conn.execute("CREATE TABLE IF NOT EXISTS hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))")
            log.info("DB: Creating index hint_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS hint_index on hints(hint)")

            # Check if legacy coin_parent_index index exists
            async with conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'coin_parent_index'"
            ) as cursor:
                self._has_coin_parent_index = await cursor.fetchone() is not None

            async with conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'coin_record_ph_ff_unspent_idx'"
            ) as cursor:
                has_ff_unspent_idx = await cursor.fetchone() is not None
            if has_ff_unspent_idx:
                self._unspent_lineage_for_ph_idx = "coin_record_ph_ff_unspent_idx"
        return self

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
                    coin = row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.add(CoinRecord(coin, row[0], spent_index, row[2] != 0, row[6]))
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
                    coin = row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.add(CoinRecord(coin, row[0], spent_index, row[2] != 0, row[6]))
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
                    coin = row_to_coin(row)
                    spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                    coins.add(CoinRecord(coin, row[0], spent_index, row[2] != 0, row[6]))

        return list(coins)

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
                        coins.add(row_to_coin_state(row))

                if len(coins) >= max_items:
                    break

        return coins

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
        *,
        max_items: int = 50000,
    ) -> list[CoinRecord]:
        if len(parent_ids) == 0:
            return []

        coins: set[CoinRecord] = set()
        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(parent_ids, SQLITE_MAX_VARIABLE_NUMBER - 3):
                parent_ids_db = tuple(batch.entries)
                parent_ids_placeholders = ",".join("?" * len(parent_ids_db))
                if self._has_coin_parent_index:
                    query = f"""
                        SELECT
                            confirmed_index, spent_index, coinbase,
                            puzzle_hash, coin_parent, amount, timestamp
                        FROM coin_record INDEXED BY coin_parent_index
                        WHERE
                            coin_parent IN ({parent_ids_placeholders})
                            AND confirmed_index >= ? AND confirmed_index < ?
                            {"" if include_spent_coins else "AND spent_index <= 0"}
                        LIMIT ?
                    """
                else:
                    query = f"""
                        SELECT
                            child.confirmed_index, child.spent_index,
                            child.coinbase, child.puzzle_hash,
                            child.coin_parent, child.amount, child.timestamp
                        FROM coin_record AS parent INDEXED BY sqlite_autoindex_coin_record_1
                        JOIN coin_record AS child INDEXED BY coin_confirmed_index
                            ON child.confirmed_index = parent.spent_index
                            AND child.coin_parent = parent.coin_name
                        WHERE
                            parent.coin_name IN ({parent_ids_placeholders})
                            AND parent.spent_index > 0
                            AND parent.spent_index >= ?
                            AND parent.spent_index < ?
                            {"" if include_spent_coins else "AND child.spent_index <= 0"}
                        LIMIT ?
                    """
                async with conn.execute(
                    query, (*parent_ids_db, start_height, end_height, max_items - len(coins))
                ) as cursor:
                    async for row in cursor:
                        coin = row_to_coin(row)
                        spent_index = uint32(0) if row[1] <= 0 else uint32(row[1])
                        coins.add(CoinRecord(coin, row[0], spent_index, row[2] != 0, row[6]))
                if len(coins) >= max_items:
                    break

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
                        coins.append(row_to_coin_state(row))
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
    ) -> tuple[list[CoinState], uint32 | None]:
        """
        Returns the coin states, as well as the next block height (or `None` if finished).
        You cannot exceed `ExplorerStore.MAX_PUZZLE_HASH_BATCH_SIZE` puzzle hashes in the query.
        """

        # This should be able to be changed later without breaking the protocol.
        # We have a small deduction for other variables to be added to the query.
        assert len(puzzle_hashes) <= ExplorerStore.MAX_PUZZLE_HASH_BATCH_SIZE

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
                coin_state = row_to_coin_state(row)
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
                    coin_state = row_to_coin_state(row)
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

    # Lookup the most recent unspent lineage that matches a puzzle hash
    async def get_unspent_lineage_info_for_puzzle_hash(self, puzzle_hash: bytes32) -> UnspentLineageInfo | None:
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

    async def get_coin_ids(self, hint: bytes, *, max_items: int = 50000) -> list[bytes32]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT coin_id from hints WHERE hint=? LIMIT ?", (hint, max_items))
            rows = await cursor.fetchall()
            await cursor.close()
        return [bytes32(row[0]) for row in rows]

    async def get_coin_ids_multi(self, hints: set[bytes], *, max_items: int = 50000) -> list[bytes32]:
        coin_ids: list[bytes32] = []

        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(hints, SQLITE_MAX_VARIABLE_NUMBER):
                hints_db: tuple[bytes, ...] = tuple(batch.entries)
                cursor = await conn.execute(
                    f"SELECT coin_id from hints INDEXED BY hint_index "
                    f"WHERE hint IN ({'?,' * (len(batch.entries) - 1)}?) LIMIT ?",
                    (*hints_db, max_items - len(coin_ids)),
                )
                rows = await cursor.fetchall()
                coin_ids.extend([bytes32(row[0]) for row in rows])
                await cursor.close()
                if len(coin_ids) >= max_items:
                    break

        return coin_ids

    async def get_coin_ids_by_hints(self, hints: Collection[bytes]) -> set[bytes32]:
        coin_ids: set[bytes32] = set()
        if len(hints) == 0:
            return coin_ids

        # use a single read transaction so all batches see a consistent view
        async with self.db_wrapper.reader() as conn:
            # to_batches only supports list and set at runtime; hints may be any Collection
            for batch in to_batches(list(hints), SQLITE_MAX_VARIABLE_NUMBER):
                hints_db: tuple[bytes, ...] = tuple(batch.entries)
                cursor = await conn.execute(
                    f"SELECT coin_id from hints INDEXED BY hint_index "
                    f"WHERE hint IN ({'?,' * (len(batch.entries) - 1)}?)",
                    hints_db,
                )
                for row in await cursor.fetchall():
                    coin_ids.add(bytes32(row[0]))
                await cursor.close()

        return coin_ids

    async def get_hints(self, coin_ids: list[bytes32]) -> list[bytes32]:
        hints: list[bytes32] = []

        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(coin_ids, SQLITE_MAX_VARIABLE_NUMBER):
                coin_ids_db: tuple[bytes32, ...] = tuple(batch.entries)
                cursor = await conn.execute(
                    f"SELECT hint from hints WHERE coin_id IN ({'?,' * (len(batch.entries) - 1)}?)",
                    coin_ids_db,
                )
                rows = await cursor.fetchall()
                hints.extend([bytes32(row[0]) for row in rows if len(row[0]) == 32])
                await cursor.close()

        return hints

    async def add_hints(self, coin_hint_list: list[tuple[bytes32, bytes]]) -> None:
        if len(coin_hint_list) == 0:
            return None

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.executemany(
                "INSERT OR IGNORE INTO hints VALUES(?, ?)",
                coin_hint_list,
            )
            await cursor.close()

    async def count_hints(self) -> int:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("select count(*) from hints") as cursor:
                row = await cursor.fetchone()

        assert row is not None

        [count] = row
        return int(count)
