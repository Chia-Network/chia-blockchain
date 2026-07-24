from __future__ import annotations

import dataclasses
import logging
from collections.abc import Collection

import typing_extensions
from chia_rs.sized_bytes import bytes32

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
