from time import perf_counter
from typing import List, Optional, Tuple

from databases import Database
import logging

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.db_wrapper import DBWrapper
from chia.util.errors import Err
from chia.util.ints import uint8, uint32
from chia.util import dialect_utils
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.trade_status import TradeStatus


async def migrate_is_my_offer(log: logging.Logger, db_connection: Database) -> None:
    """
    Migrate the is_my_offer property contained in the serialized TradeRecord (trade_record column)
    to the is_my_offer column in the trade_records table.
    """
    log.info("Beginning migration of is_my_offer property in trade_records")

    start_time = perf_counter()

    rows = await db_connection.fetch_all("SELECT trade_record, trade_id from trade_records")

    updates: List[Tuple[int, str]] = []
    for row in rows:
        record = TradeRecord.from_bytes(row[0])
        is_my_offer = 1 if record.is_my_offer else 0
        updates.append({"is_my_offer": is_my_offer, "trade_id":  row[1]})

    try:
        await db_connection.execute_many(
            "UPDATE trade_records SET is_my_offer=:is_my_offer WHERE trade_id=:trade_id",
            updates,
        )
    except:
        log.exception("Failed to migrate is_my_offer property in trade_records")
        raise

    end_time = perf_counter()
    log.info(f"Completed migration of {len(updates)} records in {end_time - start_time} seconds")


class TradeStore:
    """
    TradeStore stores trading history.
    """

    db_connection: Database
    cache_size: uint32
    db_wrapper: DBWrapper
    log: logging.Logger

    @classmethod
    async def create(
        cls,
        db_wrapper: DBWrapper,
        cache_size: uint32 = uint32(600000),
        name: str = None,
    ) -> "TradeStore":
        self = cls()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper
        self.db_connection = db_wrapper.db
        async with self.db_connection.connection() as connection:
            async with connection.transaction():
                await self.db_connection.execute(
                    (
                        "CREATE TABLE IF NOT EXISTS trade_records("
                        f" trade_record {dialect_utils.data_type('blob', self.db_connection.url.dialect)},"
                        f" trade_id {dialect_utils.data_type('text-as-index', self.db_connection.url.dialect)} PRIMARY KEY,"
                        " status int,"
                        " confirmed_at_index int,"
                        " created_at_time bigint,"
                        " sent int,"
                        f" is_my_offer {dialect_utils.data_type('tinyint', self.db_connection.url.dialect)})"
                    )
                )

                # Attempt to add the is_my_offer column. If successful, migrate is_my_offer to the new column.
                needs_is_my_offer_migration: bool = False
                try:
                    await self.db_connection.execute(f"ALTER TABLE trade_records ADD COLUMN is_my_offer {dialect_utils.data_type('tinyint', self.db_connection.url.dialect)}")
                    needs_is_my_offer_migration = True
                except:
                    pass  # ignore what is likely Duplicate column error

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'trade_confirmed_index', 'trade_records', ['confirmed_at_index'])
                await dialect_utils.create_index_if_not_exists(self.db_connection, 'trade_status', 'trade_records', ['status'])
                await dialect_utils.create_index_if_not_exists(self.db_connection, 'trade_id', 'trade_records', ['trade_id'])

        if needs_is_my_offer_migration:
            await migrate_is_my_offer(self.log, self.db_connection)

        return self

    async def _clear_database(self):
        await self.db_connection.execute("DELETE FROM trade_records")

    async def add_trade_record(self, record: TradeRecord, in_transaction) -> None:
        """
        Store TradeRecord into DB
        """
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            row_to_insert = {
                "trade_record": bytes(record),
                "trade_id": record.trade_id.hex(),
                "status": int(record.status),
                "confirmed_at_index": int(record.confirmed_at_index),
                "created_at_time": int(record.created_at_time),
                "sent": int(record.sent),
                "is_my_offer": record.is_my_offer
            }
            await self.db_connection.execute(
                dialect_utils.upsert_query('trade_records', ['trade_id'], row_to_insert.keys(), self.db_connection.url.dialect),
                row_to_insert
            )
        finally:
            if not in_transaction:
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
            is_my_offer=current.is_my_offer,
            sent=current.sent,
            offer=current.offer,
            taken_offer=current.taken_offer,
            coins_of_interest=current.coins_of_interest,
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
            is_my_offer=current.is_my_offer,
            sent=uint32(current.sent + 1),
            offer=current.offer,
            taken_offer=current.taken_offer,
            coins_of_interest=current.coins_of_interest,
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
            is_my_offer=current.is_my_offer,
            sent=uint32(0),
            offer=current.offer,
            taken_offer=current.taken_offer,
            coins_of_interest=current.coins_of_interest,
            trade_id=current.trade_id,
            status=uint32(TradeStatus.PENDING_CONFIRM.value),
            sent_to=[],
        )

        await self.add_trade_record(tx, False)

    async def get_trades_count(self) -> Tuple[int, int, int]:
        """
        Returns the number of trades in the database broken down by is_my_offer status
        """
        query = "SELECT COUNT(*) AS total, "
        query += "SUM(CASE WHEN is_my_offer=1 THEN 1 ELSE 0 END) AS my_offers, "
        query += "SUM(CASE WHEN is_my_offer=0 THEN 1 ELSE 0 END) AS taken_offers "
        query += "FROM trade_records"

        row = await self.db_connection.fetch_one(query)

        if row is None:
            return 0, 0, 0

        return int(row[0]), int(row[1]), int(row[2])

    async def get_trade_record(self, trade_id: bytes32) -> Optional[TradeRecord]:
        """
        Checks DB for TradeRecord with id: id and returns it.
        """
        row = await self.db_connection.fetch_one("SELECT * from trade_records WHERE trade_id=:trade_id", {"trade_id": trade_id.hex()})
        if row is not None:
            record = TradeRecord.from_bytes(row[0])
            return record
        return None

    async def get_trade_record_with_status(self, status: TradeStatus) -> List[TradeRecord]:
        """
        Checks DB for TradeRecord with id: id and returns it.
        """
        rows = await self.db_connection.fetch_all("SELECT * from trade_records WHERE status=:status", {"status": status.value})
        records = []
        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_not_sent(self) -> List[TradeRecord]:
        """
        Returns the list of trades that have not been received by full node yet.
        """

        rows = await self.db_connection.fetch_all(
            "SELECT * from trade_records WHERE sent<:sent and confirmed=:confirmed",
            {
                "sent": 4,
                "confirmed": 0,
            }
        )
        records = []
        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_all_unconfirmed(self) -> List[TradeRecord]:
        """
        Returns the list of all trades that have not yet been confirmed.
        """

        rows = await self.db_connection.fetch_all("SELECT * from trade_records WHERE confirmed=confirmed", {"confirmed": 0})
        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_all_trades(self) -> List[TradeRecord]:
        """
        Returns all stored trades.
        """

        rows = await self.db_connection.fetch_all("SELECT * from trade_records")
        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_trades_between(
        self,
        start: int,
        end: int,
        *,
        sort_key: Optional[str] = None,
        reverse: bool = False,
        exclude_my_offers: bool = False,
        exclude_taken_offers: bool = False,
        include_completed: bool = False,
    ) -> List[TradeRecord]:
        """
        Return a list of trades sorted by a key and between a start and end index.
        """
        if start < 0:
            raise ValueError("start must be >= 0")

        if start > end:
            raise ValueError("start must be less than or equal to end")

        # If excluding everything, return an empty list
        if exclude_my_offers and exclude_taken_offers:
            return []

        offset = start
        limit = end - start
        where_status_clause: Optional[str] = None
        order_by_clause: Optional[str] = None

        if not include_completed:
            # Construct a WHERE clause that only looks at active/pending statuses
            where_status_clause = (
                f"(status={TradeStatus.PENDING_ACCEPT.value} OR "
                f"status={TradeStatus.PENDING_CONFIRM.value} OR "
                f"status={TradeStatus.PENDING_CANCEL.value}) "
            )

        # Create an ORDER BY clause according to the desired sort type
        if sort_key is None or sort_key == "CONFIRMED_AT_HEIGHT":
            order_by_clause = (
                f"ORDER BY confirmed_at_index {'ASC' if reverse else 'DESC'}, "
                f"trade_id {'DESC' if reverse else 'ASC'} "
            )
        elif sort_key == "RELEVANCE":
            # Custom sort order for statuses to separate out pending/completed offers
            ordered_statuses = [
                # Pending statuses are grouped together and ordered by creation date/confirmation height
                (TradeStatus.PENDING_ACCEPT.value, 1 if reverse else 0),
                (TradeStatus.PENDING_CONFIRM.value, 1 if reverse else 0),
                (TradeStatus.PENDING_CANCEL.value, 1 if reverse else 0),
                # Cancelled/Confirmed/Failed are grouped together and ordered by creation date/confirmation height
                (TradeStatus.CANCELLED.value, 0 if reverse else 1),
                (TradeStatus.CONFIRMED.value, 0 if reverse else 1),
                (TradeStatus.FAILED.value, 0 if reverse else 1),
            ]
            if reverse:
                ordered_statuses.reverse()
            # Create the "WHEN {status} THEN {index}" cases for the "CASE status" statement
            ordered_status_clause = " ".join(map(lambda x: f"WHEN {x[0]} THEN {x[1]}", ordered_statuses))
            ordered_status_clause = f"CASE status {ordered_status_clause} END, "
            order_by_clause = (
                f"ORDER BY "
                f"{ordered_status_clause} "
                f"created_at_time {'ASC' if reverse else 'DESC'}, "
                f"confirmed_at_index {'ASC' if reverse else 'DESC'}, "
                f"trade_id {'DESC' if reverse else 'ASC'} "
            )
        else:
            raise ValueError(f"No known sort {sort_key}")

        query = "SELECT * from trade_records "
        args = {}

        if exclude_my_offers or exclude_taken_offers:
            # We check if exclude_my_offers == exclude_taken_offers earlier and return [] if so
            is_my_offer_val = 0 if exclude_my_offers else 1
            args["is_my_offer_val"] = is_my_offer_val

            query += "WHERE is_my_offer=:is_my_offer_val "
            # Include the additional WHERE status clause if we're filtering out certain statuses
            if where_status_clause is not None:
                query += "AND " + where_status_clause
        else:
            query = "SELECT * from trade_records "
            # Include the additional WHERE status clause if we're filtering out certain statuses
            if where_status_clause is not None:
                query += "WHERE " + where_status_clause

        # Include the ORDER BY clause
        if order_by_clause is not None:
            query += order_by_clause
        # Include the LIMIT clause
        query += "LIMIT :limit OFFSET :offset"

        args["limit"] = limit
        args["offset"] = offset

        rows = await self.db_connection.fetch_all(query, args)

        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_trades_above(self, height: uint32) -> List[TradeRecord]:
        rows = await self.db_connection.fetch_all("SELECT * from trade_records WHERE confirmed_at_index>:min_confirmed_at_index", {"min_confirmed_at_index": height})
        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def rollback_to_block(self, block_index):

        # Delete from storage
        await self.db_connection.execute(
            "DELETE FROM trade_records WHERE confirmed_at_index>:min_confirmed_at_index", {"min_confirmed_at_index": int(block_index)}
        )
