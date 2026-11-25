from __future__ import annotations

import dataclasses
import logging
from collections.abc import Collection
from typing import TYPE_CHECKING, ClassVar, cast

import typing_extensions
from chia_rs import CoinRecord, CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.full_node.coin_store import CoinStore
from chia.full_node.explorer_store_protocol import ExplorerStoreProtocol
from chia.types.mempool_item import UnspentLineageInfo
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2

log = logging.getLogger(__name__)


@typing_extensions.final
@dataclasses.dataclass
class HintStore:
    """
    The SQLite explorer store: hints, plus the explorer coin queries, which
    it forwards to the SQLite CoinStore whose database it shares. Replacing
    the coin store's backend means replacing that forwarding here; callers
    of ExplorerStoreProtocol don't change.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ExplorerStoreProtocol] = cast("HintStore", None)

    coin_store: CoinStore

    @property
    def db_wrapper(self) -> DBWrapper2:
        return self.coin_store.db_wrapper

    @classmethod
    async def create(cls, coin_store: CoinStore) -> HintStore:
        db_wrapper = coin_store.db_wrapper
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"HintStore does not support database schema v{db_wrapper.db_version}")

        self = HintStore(coin_store)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            log.info("DB: Creating hint store tables and indexes.")
            await conn.execute("CREATE TABLE IF NOT EXISTS hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))")
            log.info("DB: Creating index hint_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS hint_index on hints(hint)")
        return self

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

    async def get_coin_record(self, coin_name: bytes32) -> CoinRecord | None:
        return await self.coin_store.get_coin_record(coin_name)

    async def get_coin_records_by_puzzle_hash(
        self,
        include_spent_coins: bool,
        puzzle_hash: bytes32,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        return await self.coin_store.get_coin_records_by_puzzle_hash(
            include_spent_coins, puzzle_hash, start_height, end_height
        )

    async def get_coin_records_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        return await self.coin_store.get_coin_records_by_puzzle_hashes(
            include_spent_coins, puzzle_hashes, start_height, end_height
        )

    async def get_coin_records_by_names(
        self,
        include_spent_coins: bool,
        names: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        return await self.coin_store.get_coin_records_by_names(include_spent_coins, names, start_height, end_height)

    async def get_coin_states_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: set[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_items: int = 50000,
    ) -> set[CoinState]:
        return await self.coin_store.get_coin_states_by_puzzle_hashes(
            include_spent_coins, puzzle_hashes, min_height, max_items=max_items
        )

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
        *,
        max_items: int = 50000,
    ) -> list[CoinRecord]:
        return await self.coin_store.get_coin_records_by_parent_ids(
            include_spent_coins, parent_ids, start_height, end_height, max_items=max_items
        )

    async def get_coin_states_by_ids(
        self,
        include_spent_coins: bool,
        coin_ids: Collection[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_height: uint32 = uint32.MAXIMUM,
        max_items: int = 50000,
    ) -> list[CoinState]:
        return await self.coin_store.get_coin_states_by_ids(
            include_spent_coins, coin_ids, min_height, max_height=max_height, max_items=max_items
        )

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
        return await self.coin_store.batch_coin_states_by_puzzle_hashes(
            puzzle_hashes,
            min_height=min_height,
            include_spent=include_spent,
            include_unspent=include_unspent,
            include_hinted=include_hinted,
            min_amount=min_amount,
            max_items=max_items,
        )

    async def get_unspent_lineage_info_for_puzzle_hash(self, puzzle_hash: bytes32) -> UnspentLineageInfo | None:
        return await self.coin_store.get_unspent_lineage_info_for_puzzle_hash(puzzle_hash)
