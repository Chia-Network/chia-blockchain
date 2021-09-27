from typing import List, Tuple
import aiosqlite
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
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
        # the coin_id is unique, same hint can be used for multiple coins
        await self.coin_record_db.execute(("CREATE TABLE IF NOT EXISTS hints(coin_id text PRIMARY KEY,  hint text)"))
        await self.coin_record_db.execute("CREATE INDEX IF NOT EXISTS hint_index on hints(hint)")
        await self.coin_record_db.commit()
        return self

    async def get_hints(self, hint: bytes) -> List[bytes32]:
        cursor = await self.coin_record_db.execute("SELECT * from hints WHERE hint=?", (hint.hex(),))
        rows = await cursor.fetchall()
        await cursor.close()
        coin_ids = []
        for row in rows:
            coin_id = row[0]
            coin_ids.append(hexstr_to_bytes(row[0]))
        return coin_ids

    async def add_hints(self, coin_hint_list: List[Tuple[str, str]]) -> None:
        cursor = await self.coin_record_db.executemany(
            "INSERT INTO hints VALUES(?, ?)",
            coin_hint_list,
        )
        await cursor.close()
