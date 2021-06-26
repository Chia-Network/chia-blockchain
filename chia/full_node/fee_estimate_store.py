from typing import Any, Optional
import aiosqlite

from chia.full_node.fee_estimate import FeeTrackerBackup
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32


class FeeStore:
    """
    This object stores Fee Stats
    """

    db: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()
        self.db_wrapper = db_wrapper
        self.db = db_wrapper.db
        await self.db.execute(("CREATE TABLE IF NOT EXISTS fee_records(" "type text PRIMARY KEY," "fee_backup blob)"))

        await self.db.commit()
        return self

    async def get_stored_fee_data(self, type: str = "backup") -> Optional[FeeTrackerBackup]:
        cursor = await self.db.execute("SELECT * from fee_records WHERE type=?", (type,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            backup = FeeTrackerBackup.from_bytes(row[1])
            return backup
        return None

    async def store_fee_data(self, fee_backup: FeeTrackerBackup, type: str = "backup") -> Any:
        cursor = await self.db.execute(
            f"INSERT OR REPLACE INTO coin_record VALUES(?, ?)",
            (type, bytes(fee_backup)),
        )
        await cursor.close()
