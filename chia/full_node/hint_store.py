from __future__ import annotations

import dataclasses
import logging
from typing import List, Set, Tuple

import typing_extensions

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2

log = logging.getLogger(__name__)


@typing_extensions.final
@dataclasses.dataclass
class HintStore:
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> HintStore:
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"HintStore does not support database schema v{db_wrapper.db_version}")

        self = HintStore(db_wrapper)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            log.info("DB: Creating hint store tables and indexes.")
            await conn.execute("CREATE TABLE IF NOT EXISTS hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))")
            log.info("DB: Creating index hint_index")
            await conn.execute("CREATE INDEX IF NOT EXISTS hint_index on hints(hint)")
        return self

    async def get_coin_ids(self, hint: bytes, *, max_items: int = 50000) -> List[bytes32]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT coin_id from hints WHERE hint=? LIMIT ?", (hint, max_items))
            rows = await cursor.fetchall()
            await cursor.close()
        return [bytes32(row[0]) for row in rows]

    async def get_coin_ids_multi(self, hints: Set[bytes], *, max_items: int = 50000) -> List[bytes32]:
        coin_ids: List[bytes32] = []

        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(hints, SQLITE_MAX_VARIABLE_NUMBER):
                hints_db: Tuple[bytes, ...] = tuple(batch.entries)
                cursor = await conn.execute(
                    f"SELECT coin_id from hints INDEXED BY hint_index "
                    f'WHERE hint IN ({"?," * (len(batch.entries) - 1)}?) LIMIT ?',
                    hints_db + (max_items,),
                )
                rows = await cursor.fetchall()
                coin_ids.extend([bytes32(row[0]) for row in rows])
                await cursor.close()

        return coin_ids

    async def get_hints(self, coin_ids: List[bytes32]) -> List[bytes32]:
        hints: List[bytes32] = []

        async with self.db_wrapper.reader_no_transaction() as conn:
            for batch in to_batches(coin_ids, SQLITE_MAX_VARIABLE_NUMBER):
                coin_ids_db: Tuple[bytes32, ...] = tuple(batch.entries)
                cursor = await conn.execute(
                    f'SELECT hint from hints WHERE coin_id IN ({"?," * (len(batch.entries) - 1)}?)',
                    coin_ids_db,
                )
                rows = await cursor.fetchall()
                hints.extend([bytes32(row[0]) for row in rows if len(row[0]) == 32])
                await cursor.close()

        return hints

    async def add_hints(self, coin_hint_list: List[Tuple[bytes32, bytes]]) -> None:
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
