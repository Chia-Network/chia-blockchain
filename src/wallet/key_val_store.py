from typing import Optional, Any

import aiosqlite
from src.util.streamable import Streamable


class KeyValStore:
    """
    Multipurpose persistent key-value store
    """

    db_connection: aiosqlite.Connection

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        self.db_connection = connection

        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS key_val_store("
                " key text PRIMARY KEY,"
                " value text)"
            )
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS name on key_val_store(key)"
        )

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM key_val_store")
        await cursor.close()
        await self.db_connection.commit()

    async def get(self, key: str, obj_class: Any = None) -> Optional[str]:
        """
        Return bytes representation of stored object
        """

        cursor = await self.db_connection.execute(
            "SELECT * from key_val_store WHERE key=?", (key,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        return row[1]

    async def set(self, key: str, obj: Streamable):
        """
        Adds object to key val store
        """
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO key_val_store VALUES(?, ?)",
            (key, bytes(obj).hex()),
        )
        await cursor.close()
        await self.db_connection.commit()
