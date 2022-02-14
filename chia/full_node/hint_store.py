from typing import List, Tuple
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
import logging

log = logging.getLogger(__name__)


class HintStore:
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()
        self.db_wrapper = db_wrapper

        if self.db_wrapper.db_version == 2:
            await self.db_wrapper.db.execute(
                "CREATE TABLE IF NOT EXISTS hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))"
            )
        else:
            await self.db_wrapper.db.execute(
                "CREATE TABLE IF NOT EXISTS hints(id INTEGER PRIMARY KEY AUTOINCREMENT, coin_id blob, hint blob)"
            )
        await self.db_wrapper.db.execute("CREATE INDEX IF NOT EXISTS hint_index on hints(hint)")
        await self.db_wrapper.db.commit()
        return self

    async def get_coin_ids(self, hint: bytes) -> List[bytes32]:
        cursor = await self.db_wrapper.db.execute("SELECT coin_id from hints WHERE hint=?", (hint,))
        rows = await cursor.fetchall()
        await cursor.close()
        coin_ids = []
        for row in rows:
            coin_ids.append(row[0])
        return coin_ids

    async def add_hints(self, coin_hint_list: List[Tuple[bytes32, bytes]]) -> None:
        if self.db_wrapper.db_version == 2:
            cursor = await self.db_wrapper.db.executemany(
                "INSERT OR IGNORE INTO hints VALUES(?, ?)",
                coin_hint_list,
            )
        else:
            cursor = await self.db_wrapper.db.executemany(
                "INSERT INTO hints VALUES(?, ?, ?)",
                [(None,) + record for record in coin_hint_list],
            )
        await cursor.close()

    async def count_hints(self) -> int:
        async with self.db_wrapper.db.execute("select count(*) from hints") as cursor:
            row = await cursor.fetchone()

        assert row is not None

        [count] = row
        return int(count)
