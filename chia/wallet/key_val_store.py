from typing import Any

from chia.util.db_wrapper import DBWrapper2


class KeyValStore:
    """
    Multipurpose persistent key-value store
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2):
        self = cls()
        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS key_val_store(" " key text PRIMARY KEY," " value blob)")

            await conn.execute("CREATE INDEX IF NOT EXISTS key_val_name on key_val_store(key)")

        return self

    async def get_object(self, key: str, object_type: Any) -> Any:
        """
        Return bytes representation of stored object
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from key_val_store WHERE key=?", (key,))
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return object_type.from_bytes(row[1])

    async def set_object(self, key: str, obj: Any):
        """
        Adds object to key val store. Obj MUST support __bytes__ and bytes() methods.
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO key_val_store VALUES(?, ?)",
                (key, bytes(obj)),
            )
            await cursor.close()

    async def remove_object(self, key: str):
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute("DELETE FROM key_val_store where key=?", (key,))
            await cursor.close()
