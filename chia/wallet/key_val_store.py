from typing import Any

import aiosqlite

from chia.util.db_wrapper import DBWrapper
from chia.util.streamable import Streamable


class KeyValStore:
    """
    Multipurpose persistent key-value store
    """

    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()
        self.db_wrapper = db_wrapper
        self.db_connection = db_wrapper.db
        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS key_val_store(" " key text PRIMARY KEY," " value blob)"
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS name on key_val_store(key)")

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM key_val_store")
        await cursor.close()
        await self.db_connection.commit()

    async def get_object(self, key: str, object_type: Any) -> Any:
        """
        Return bytes representation of stored object
        """

        cursor = await self.db_connection.execute("SELECT * from key_val_store WHERE key=?", (key,))
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        return object_type.from_bytes(row[1])

    async def set_object(self, key: str, obj: Streamable):
        """
        Adds object to key val store
        """
        async with self.db_wrapper.lock:
            cursor = await self.db_connection.execute(
                "INSERT OR REPLACE INTO key_val_store VALUES(?, ?)",
                (key, bytes(obj)),
            )
            await cursor.close()
            await self.db_connection.commit()

    async def remove_object(self, key: str):
        cursor = await self.db_connection.execute("DELETE FROM key_val_store where key=?", (key,))
        await cursor.close()
        await self.db_connection.commit()
