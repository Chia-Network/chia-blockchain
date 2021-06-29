from typing import List, Optional

import aiosqlite

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.db_wrapper import DBWrapper
from chia.util.errors import Err
from chia.util.ints import uint8, uint32
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.trade_status import TradeStatus


class TradeStore:
    """
    TradeStore stores trading history.
    """

    db_connection: aiosqlite.Connection
    cache_size: uint32
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper
        self.db_connection = db_wrapper.db

        await self.db_connection.execute("pragma journal_mode=wal")
        await self.db_connection.execute("pragma synchronous=2")
        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS trade_records("
                " trade_record blob,"
                " trade_id text PRIMARY KEY,"
                " status int,"
                " confirmed_at_index int,"
                " created_at_time bigint,"
                " sent int)"
            )
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS trade_confirmed_index on trade_records(confirmed_at_index)"
        )
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS trade_status on trade_records(status)")
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS trade_id on trade_records(trade_id)")

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM trade_records")
        await cursor.close()
        await self.db_connection.commit()

    async def add_trade_record(self, record: TradeRecord, in_transaction) -> None:
        """
        Store TradeRecord into DB
        """
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute(
                "INSERT OR REPLACE INTO trade_records VALUES(?, ?, ?, ?, ?, ?)",
                (
                    bytes(record),
                    record.trade_id.hex(),
                    record.status,
                    record.confirmed_at_index,
                    record.created_at_time,
                    record.sent,
                ),
            )
            await cursor.close()
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()

    async def set_status(self, trade_id: bytes32, status: TradeStatus, in_transaction: bool, index: uint32 = uint32(0)):
        """
        Updates the status of the trade
        """
        current: Optional[TradeRecord] = await self.get_trade_record(trade_id)
        if current is None:
            return None
        confirmed_at_index = current.confirmed_at_index
        if index != 0:
            confirmed_at_index = index
        tx: TradeRecord = TradeRecord(
            confirmed_at_index=confirmed_at_index,
            accepted_at_time=current.accepted_at_time,
            created_at_time=current.created_at_time,
            my_offer=current.my_offer,
            sent=current.sent,
            spend_bundle=current.spend_bundle,
            tx_spend_bundle=current.tx_spend_bundle,
            additions=current.additions,
            removals=current.removals,
            trade_id=current.trade_id,
            status=uint32(status.value),
            sent_to=current.sent_to,
        )
        await self.add_trade_record(tx, in_transaction)

    async def increment_sent(
        self,
        id: bytes32,
        name: str,
        send_status: MempoolInclusionStatus,
        err: Optional[Err],
    ) -> bool:
        """
        Updates trade sent count (Full Node has received spend_bundle and sent ack).
        """

        current: Optional[TradeRecord] = await self.get_trade_record(id)
        if current is None:
            return False

        sent_to = current.sent_to.copy()

        err_str = err.name if err is not None else None
        append_data = (name, uint8(send_status.value), err_str)

        # Don't increment count if it's already sent to this peer
        if append_data in sent_to:
            return False

        sent_to.append(append_data)

        tx: TradeRecord = TradeRecord(
            confirmed_at_index=current.confirmed_at_index,
            accepted_at_time=current.accepted_at_time,
            created_at_time=current.created_at_time,
            my_offer=current.my_offer,
            sent=uint32(current.sent + 1),
            spend_bundle=current.spend_bundle,
            tx_spend_bundle=current.tx_spend_bundle,
            additions=current.additions,
            removals=current.removals,
            trade_id=current.trade_id,
            status=current.status,
            sent_to=sent_to,
        )

        await self.add_trade_record(tx, False)
        return True

    async def set_not_sent(self, id: bytes32):
        """
        Updates trade sent count to 0.
        """

        current: Optional[TradeRecord] = await self.get_trade_record(id)
        if current is None:
            return None

        tx: TradeRecord = TradeRecord(
            confirmed_at_index=current.confirmed_at_index,
            accepted_at_time=current.accepted_at_time,
            created_at_time=current.created_at_time,
            my_offer=current.my_offer,
            sent=uint32(0),
            spend_bundle=current.spend_bundle,
            tx_spend_bundle=current.tx_spend_bundle,
            additions=current.additions,
            removals=current.removals,
            trade_id=current.trade_id,
            status=uint32(TradeStatus.PENDING_CONFIRM.value),
            sent_to=[],
        )

        await self.add_trade_record(tx, False)

    async def get_trade_record(self, trade_id: bytes32) -> Optional[TradeRecord]:
        """
        Checks DB for TradeRecord with id: id and returns it.
        """
        cursor = await self.db_connection.execute("SELECT * from trade_records WHERE trade_id=?", (trade_id.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            record = TradeRecord.from_bytes(row[0])
            return record
        return None

    async def get_trade_record_with_status(self, status: TradeStatus) -> List[TradeRecord]:
        """
        Checks DB for TradeRecord with id: id and returns it.
        """
        cursor = await self.db_connection.execute("SELECT * from trade_records WHERE status=?", (status.value,))
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_not_sent(self) -> List[TradeRecord]:
        """
        Returns the list of trades that have not been received by full node yet.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from trade_records WHERE sent<? and confirmed=?",
            (
                4,
                0,
            ),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_all_unconfirmed(self) -> List[TradeRecord]:
        """
        Returns the list of all trades that have not yet been confirmed.
        """

        cursor = await self.db_connection.execute("SELECT * from trade_records WHERE confirmed=?", (0,))
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_all_trades(self) -> List[TradeRecord]:
        """
        Returns all stored trades.
        """

        cursor = await self.db_connection.execute("SELECT * from trade_records")
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_trades_above(self, height: uint32) -> List[TradeRecord]:
        cursor = await self.db_connection.execute("SELECT * from trade_records WHERE confirmed_at_index>?", (height,))
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def rollback_to_block(self, block_index):

        # Delete from storage
        cursor = await self.db_connection.execute(
            "DELETE FROM trade_records WHERE confirmed_at_index>?", (block_index,)
        )
        await cursor.close()
        await self.db_connection.commit()
