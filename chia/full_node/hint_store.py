from typing import List, Tuple
import aiosqlite
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
import logging

log = logging.getLogger(__name__)


class HintStore:
    coin_record_db: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()
        self.db_wrapper = db_wrapper
        self.coin_record_db = db_wrapper.db
        await self.coin_record_db.execute(
            "CREATE TABLE IF NOT EXISTS hints(id INTEGER PRIMARY KEY AUTOINCREMENT, coin_id blob,  hint blob)"
        )
        await self.coin_record_db.execute("CREATE INDEX IF NOT EXISTS hint_index on hints(hint)")
        await self.coin_record_db.commit()
        return self

    async def get_coin_ids(self, hint: bytes) -> List[bytes32]:
        cursor = await self.coin_record_db.execute("SELECT * from hints WHERE hint=?", (hint,))
        rows = await cursor.fetchall()
        await cursor.close()
        coin_ids = []
        for row in rows:
            coin_ids.append(row[1])
        return coin_ids

    async def add_hints(self, coin_hint_list: List[Tuple[bytes32, bytes]]) -> None:
        cursor = await self.coin_record_db.executemany(
            "INSERT INTO hints VALUES(?, ?, ?)",
            [(None,) + record for record in coin_hint_list],
        )
        await cursor.close()
