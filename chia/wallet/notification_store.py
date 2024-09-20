from __future__ import annotations

import dataclasses
import logging
import sqlite3
from typing import List, Optional, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclasses.dataclass(frozen=True)
class Notification(Streamable):
    id: bytes32
    message: bytes
    amount: uint64
    height: uint32


class NotificationStore:
    """
    NotificationStore stores trading history.
    """

    cache_size: uint32
    db_wrapper: DBWrapper2
    log: logging.Logger

    @classmethod
    async def create(
        cls, db_wrapper: DBWrapper2, cache_size: uint32 = uint32(600000), name: Optional[str] = None
    ) -> NotificationStore:
        self = cls()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS notifications(coin_id blob PRIMARY KEY, msg blob, amount blob)"
            )

            await conn.execute("CREATE TABLE IF NOT EXISTS all_notification_ids(coin_id blob PRIMARY KEY)")

            try:
                await conn.execute("ALTER TABLE notifications ADD COLUMN height bigint DEFAULT 0")
            except sqlite3.OperationalError as e:
                if "duplicate column" in e.args[0]:
                    pass  # ignore what is likely Duplicate column error
                else:
                    raise e

            # This used to be an accidentally created redundant index on coin_id which is already a primary key
            # We can remove this at some point in the future when it's unlikely this index still exists
            await conn.execute("DROP INDEX IF EXISTS coin_id_index")

        return self

    async def add_notification(self, notification: Notification) -> None:
        """
        Store Notification into DB
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO notifications (coin_id, msg, amount, height) VALUES(?, ?, ?, ?)",
                (
                    notification.id,
                    notification.message,
                    notification.amount.stream_to_bytes(),
                    notification.height,
                ),
            )
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO all_notification_ids (coin_id) VALUES(?)",
                (notification.id,),
            )
            await cursor.close()

    async def get_notifications(self, coin_ids: List[bytes32]) -> List[Notification]:
        """
        Checks DB for Notification with id: id and returns it.
        """
        coin_ids_str_list = "("
        for _ in coin_ids:
            coin_ids_str_list += "?"
            coin_ids_str_list += ","
        coin_ids_str_list = coin_ids_str_list[:-1] if len(coin_ids_str_list) > 1 else "("
        coin_ids_str_list += ")"

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT * from notifications WHERE coin_id IN {coin_ids_str_list} ORDER BY amount DESC", coin_ids
            )

        return [
            Notification(
                bytes32(row[0]),
                bytes(row[1]),
                uint64.from_bytes(row[2]),
                uint32(row[3]),
            )
            for row in rows
        ]

    async def get_all_notifications(
        self, pagination: Optional[Tuple[Optional[int], Optional[int]]] = None
    ) -> List[Notification]:
        """
        Checks DB for Notification with id: id and returns it.
        """
        if pagination is not None:
            if pagination[1] is not None and pagination[0] is not None:
                pagination_str = " LIMIT ?, ?"
                pagination_params: Tuple[int, ...] = (pagination[0], pagination[1] - pagination[0])
            elif pagination[1] is None and pagination[0] is not None:
                pagination_str = " LIMIT ?, (SELECT COUNT(*) from notifications)"
                pagination_params = (pagination[0],)
            elif pagination[1] is not None and pagination[0] is None:
                pagination_str = " LIMIT ?"
                pagination_params = (pagination[1],)
            else:
                pagination_str = ""
                pagination_params = tuple()
        else:
            pagination_str = ""
            pagination_params = tuple()

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT * from notifications ORDER BY amount DESC{pagination_str}", pagination_params
            )

        return [
            Notification(
                bytes32(row[0]),
                bytes(row[1]),
                uint64.from_bytes(row[2]),
                uint32(row[3]),
            )
            for row in rows
        ]

    async def delete_notifications(self, coin_ids: List[bytes32]) -> None:
        coin_ids_str_list = "("
        for _ in coin_ids:
            coin_ids_str_list += "?"
            coin_ids_str_list += ","
        coin_ids_str_list = coin_ids_str_list[:-1] if len(coin_ids_str_list) > 1 else "("
        coin_ids_str_list += ")"

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Delete from storage
            cursor = await conn.execute(f"DELETE FROM notifications WHERE coin_id IN {coin_ids_str_list}", coin_ids)
            await cursor.close()

    async def delete_all_notifications(self) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Delete from storage
            cursor = await conn.execute("DELETE FROM notifications")
            await cursor.close()

    async def notification_exists(self, id: bytes32) -> bool:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT EXISTS (SELECT 1 from all_notification_ids WHERE coin_id=?)", (id,)
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                exists: bool = row[0] > 0
                return exists
