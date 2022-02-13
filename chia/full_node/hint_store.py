from typing import List, Tuple
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
import logging
import os

log = logging.getLogger(__name__)


class HintStore:
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()
        self.db_wrapper = db_wrapper

        if self.db_wrapper.db_version == 2:

            with open(os.path.join(os.path.dirname(__file__), "sql/hint_store_tables_v2.sql"), "r") as table_sql_file:
                table_sql_script = table_sql_file.read()
            with open(os.path.join(os.path.dirname(__file__), "sql/hint_store_indexes_v2.sql"), "r") as index_sql_file:
                index_sql_script = index_sql_file.read()

        else:

            with open(os.path.join(os.path.dirname(__file__), "sql/hint_store_tables_v1.sql"), "r") as table_sql_file:
                table_sql_script = table_sql_file.read()
            with open(os.path.join(os.path.dirname(__file__), "sql/hint_store_indexes_v1.sql"), "r") as index_sql_file:
                index_sql_script = index_sql_file.read()

        await self.db_wrapper.db.executescript(table_sql_script)
        await self.db_wrapper.db.executescript(index_sql_script)

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
                "INSERT INTO hints VALUES(?, ?) ON CONFLICT DO NOTHING",
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
