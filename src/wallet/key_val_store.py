from typing import Any
import aiosqlite

from src.util.byte_types import hexstr_to_bytes
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
            ("CREATE TABLE IF NOT EXISTS key_val_store(" " key text PRIMARY KEY," " value text)")
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS name on key_val_store(key)")

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM key_val_store")
        await cursor.close()
        await self.db_connection.commit()

    async def get_object(self, key: str, type: Any) -> Any:
        """
        Return bytes representation of stored object
        """

        cursor = await self.db_connection.execute("SELECT * from key_val_store WHERE key=?", (key,))
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        return type.from_bytes(hexstr_to_bytes(row[1]))

    async def set_object(self, key: str, obj: Streamable):
        """
        Adds object to key val store
        """
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO key_val_store VALUES(?, ?)",
            (key, bytes(obj).hex()),
        )
        await cursor.close()
        await self.db_connection.commit()
