from typing import List, Tuple
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.util import dialect_utils
import logging

log = logging.getLogger(__name__)


class HintStore:
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()
        self.db_wrapper = db_wrapper

        async with self.db_wrapper.db.connection() as connection:
            async with connection.transaction():
                if self.db_wrapper.db_version == 2:
                    await self.db_wrapper.db.execute(
                        f"CREATE TABLE IF NOT EXISTS hints(coin_id {dialect_utils.data_type('blob-as-index', self.db_wrapper.db.url.dialect)}, hint {dialect_utils.data_type('blob-as-index', self.db_wrapper.db.url.dialect)}, UNIQUE (coin_id, hint))"
                    )
                else:
                    await self.db_wrapper.db.execute(
                        f"CREATE TABLE IF NOT EXISTS hints(id INTEGER PRIMARY KEY {dialect_utils.clause('AUTOINCREMENT', self.db_wrapper.db.url.dialect)}, coin_id {dialect_utils.data_type('blob', self.db_wrapper.db.url.dialect)}, hint {dialect_utils.data_type('blob-as-index', self.db_wrapper.db.url.dialect)})"
                    )
                await dialect_utils.create_index_if_not_exists(self.db_wrapper.db, 'hint_index', 'hints', ['hint'])
        return self

    async def get_coin_ids(self, hint: bytes) -> List[bytes32]:
        rows = await self.db_wrapper.db.fetch_all("SELECT coin_id from hints WHERE hint=:hint", {"hint": hint})
        coin_ids = []
        for row in rows:
            coin_ids.append(row[0])
        return coin_ids

    async def add_hints(self, coin_hint_list: List[Tuple[bytes32, bytes]]) -> None:
        coin_hint_list_db = list(map(lambda coin_hint: {"coin_id": coin_hint[0], "hint": coin_hint[1]}, coin_hint_list))
        if len(coin_hint_list) > 0:
            if self.db_wrapper.db_version == 2:
                await self.db_wrapper.db.execute_many(
                    dialect_utils.insert_or_ignore_query('hints', ['coin_id'], coin_hint_list_db[0].keys(), self.db_wrapper.db.url.dialect),
                    coin_hint_list_db,
                )
            else:
                await self.db_wrapper.db.execute_many(
                    "INSERT INTO hints(coin_id, hint) VALUES(:coin_id, :hint)",
                    coin_hint_list_db,
                )

    async def count_hints(self) -> int:
        row = await self.db_wrapper.db.fetch_one("select count(*) from hints")

        assert row is not None

        [count] = row
        return int(count)
