from typing import Any, Optional
import aiosqlite

from chia.full_node.fee_estimate import FeeTrackerBackup
from chia.util.db_wrapper import DBWrapper, DBWrapper2


class FeeStore:
    """
    This object stores Fee Stats
    """

    db: aiosqlite.Connection
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2):
        self = cls()
        self.db_wrapper = db_wrapper
        async with self.db_wrapper.write_db() as conn:
            await conn.execute(("CREATE TABLE IF NOT EXISTS fee_records(" "type text PRIMARY KEY," "fee_backup blob)"))

        return self

    async def get_stored_fee_data(self, type: str = "backup") -> Optional[FeeTrackerBackup]:
        async with self.db_wrapper.read_db() as conn:
            async with conn.execute("SELECT * from fee_records WHERE type=?", (type,)) as cursor:
                row = await cursor.fetchone()
                await cursor.close()
                if row is not None:
                    backup = FeeTrackerBackup.from_bytes(row[1])
                    return backup
                return None

    async def store_fee_data(self, fee_backup: FeeTrackerBackup, type: str = "backup") -> Any:
        async with self.db_wrapper.write_db() as conn:
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO fee_records VALUES(?, ?)",
                (type, bytes(fee_backup)),
            )
