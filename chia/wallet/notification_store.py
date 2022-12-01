from __future__ import annotations

import dataclasses
import logging
from typing import List, Optional, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64


@dataclasses.dataclass(frozen=True)
class Notification:
    coin_id: bytes32
    message: bytes
    amount: uint64


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
    ) -> "NotificationStore":
        self = cls()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS notifications(" "coin_id blob PRIMARY KEY," "msg blob," "amount blob" ")"
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_id_index on notifications(coin_id)")

        return self

    async def add_notification(self, notification: Notification) -> None:
        """
        Store Notification into DB
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO notifications " "(coin_id, msg, amount) " "VALUES(?, ?, ?)",
                (
                    notification.coin_id,
                    notification.message,
                    bytes(notification.amount),
                ),
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
                pagination_str = f" LIMIT {pagination[0]}, {pagination[1] - pagination[0]}"
            elif pagination[1] is None and pagination[0] is not None:
                pagination_str = f" LIMIT {pagination[0]}, (SELECT COUNT(*) from notifications)"
            elif pagination[1] is not None and pagination[0] is None:
                pagination_str = f" LIMIT {pagination[1]}"
            else:
                pagination_str = ""
        else:
            pagination_str = ""

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(f"SELECT * from notifications ORDER BY amount DESC{pagination_str}")

        return [
            Notification(
                bytes32(row[0]),
                bytes(row[1]),
                uint64.from_bytes(row[2]),
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
