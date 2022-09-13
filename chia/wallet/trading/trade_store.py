import logging
from time import perf_counter
from typing import List, Optional, Tuple, Set

import aiosqlite

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.db_wrapper import DBWrapper2
from chia.util.errors import Err
from chia.util.ints import uint8, uint32
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.trade_status import TradeStatus


async def migrate_coin_of_interest(log: logging.Logger, db: aiosqlite.Connection) -> None:
    log.info("Beginning migration of coin_of_interest_to_trade_record lookup table")

    start_time = perf_counter()
    rows = await db.execute_fetchall("SELECT trade_record, trade_id from trade_records")

    inserts: List[Tuple[bytes32, bytes32]] = []
    for row in rows:
        record: TradeRecord = TradeRecord.from_bytes(row[0])
        for coin in record.coins_of_interest:
            inserts.append((coin.name(), record.trade_id))

    if not inserts:
        # no trades to migrate
        return
    try:
        await db.executemany(
            "INSERT INTO coin_of_interest_to_trade_record " "(coin_id, trade_id) " "VALUES(?, ?)", inserts
        )
    except (aiosqlite.OperationalError, aiosqlite.IntegrityError):
        log.exception("Failed to migrate coin_of_interest lookup table for trade_records")
        raise

    end_time = perf_counter()
    log.info(
        f"Completed coin_of_interest lookup table migration of {len(inserts)} "
        f"records in {end_time - start_time} seconds"
    )


async def migrate_is_my_offer(log: logging.Logger, db_connection: aiosqlite.Connection) -> None:
    """
    Migrate the is_my_offer property contained in the serialized TradeRecord (trade_record column)
    to the is_my_offer column in the trade_records table.
    """
    log.info("Beginning migration of is_my_offer property in trade_records")

    start_time = perf_counter()
    cursor = await db_connection.execute("SELECT trade_record, trade_id from trade_records")
    rows = await cursor.fetchall()
    await cursor.close()

    updates: List[Tuple[int, str]] = []
    for row in rows:
        record = TradeRecord.from_bytes(row[0])
        is_my_offer = 1 if record.is_my_offer else 0
        updates.append((is_my_offer, row[1]))

    try:
        await db_connection.executemany("UPDATE trade_records SET is_my_offer=? WHERE trade_id=?", updates)
    except (aiosqlite.OperationalError, aiosqlite.IntegrityError):
        log.exception("Failed to migrate is_my_offer property in trade_records")
        raise

    end_time = perf_counter()
    log.info(f"Completed migration of {len(updates)} records in {end_time - start_time} seconds")


class TradeStore:
    """
    TradeStore stores trading history.
    """

    cache_size: uint32
    db_wrapper: DBWrapper2
    log: logging.Logger

    @classmethod
    async def create(
        cls, db_wrapper: DBWrapper2, cache_size: uint32 = uint32(600000), name: Optional[str] = None
    ) -> "TradeStore":
        self = cls()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS trade_records("
                    " trade_record blob,"
                    " trade_id text PRIMARY KEY,"
                    " status int,"
                    " confirmed_at_index int,"
                    " created_at_time bigint,"
                    " sent int,"
                    " is_my_offer tinyint)"
                )
            )

            await conn.execute(
                ("CREATE TABLE IF NOT EXISTS coin_of_interest_to_trade_record(" " trade_id blob," " coin_id blob)")
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS coin_to_trade_record_index on " "coin_of_interest_to_trade_record(trade_id)"
            )

            # coin of interest migration check
            trades_not_emtpy = await (await conn.execute("SELECT trade_id FROM trade_records LIMIT 1")).fetchone()
            coins_emtpy = not await (
                await conn.execute("SELECT coin_id FROM coin_of_interest_to_trade_record LIMIT 1")
            ).fetchone()
            # run coin of interest migration if we find any existing rows in trade records
            if trades_not_emtpy and coins_emtpy:
                migrate_coin_of_interest_col = True
            else:
                migrate_coin_of_interest_col = False
            # Attempt to add the is_my_offer column. If successful, migrate is_my_offer to the new column.
            needs_is_my_offer_migration: bool = False
            try:
                await conn.execute("ALTER TABLE trade_records ADD COLUMN is_my_offer tinyint")
                needs_is_my_offer_migration = True
            except aiosqlite.OperationalError:
                pass  # ignore what is likely Duplicate column error

            await conn.execute("CREATE INDEX IF NOT EXISTS trade_confirmed_index on trade_records(confirmed_at_index)")
            await conn.execute("CREATE INDEX IF NOT EXISTS trade_status on trade_records(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS trade_id on trade_records(trade_id)")

            if needs_is_my_offer_migration:
                await migrate_is_my_offer(self.log, conn)
            if migrate_coin_of_interest_col:
                await migrate_coin_of_interest(self.log, conn)

        return self

    async def add_trade_record(self, record: TradeRecord) -> None:
        """
        Store TradeRecord into DB
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO trade_records "
                "(trade_record, trade_id, status, confirmed_at_index, created_at_time, sent, is_my_offer) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    bytes(record),
                    record.trade_id.hex(),
                    record.status,
                    record.confirmed_at_index,
                    record.created_at_time,
                    record.sent,
                    record.is_my_offer,
                ),
            )
            await cursor.close()
            # remove all current coin ids
            await conn.execute("DELETE FROM coin_of_interest_to_trade_record WHERE trade_id=?", (record.trade_id,))
            # now recreate them all
            inserts: List[Tuple[bytes32, bytes32]] = []
            for coin in record.coins_of_interest:
                inserts.append((coin.name(), record.trade_id))
            await conn.executemany(
                "INSERT INTO coin_of_interest_to_trade_record (coin_id, trade_id) VALUES(?, ?)", inserts
            )

    async def set_status(self, trade_id: bytes32, status: TradeStatus, index: uint32 = uint32(0)) -> None:
        """
        Updates the status of the trade
        """
        current: Optional[TradeRecord] = await self.get_trade_record(trade_id)
        if current is None:
            return
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
        await self.add_trade_record(tx)

    async def increment_sent(
        self, id: bytes32, name: str, send_status: MempoolInclusionStatus, err: Optional[Err]
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

        await self.add_trade_record(tx)
        return True

    async def get_trades_count(self) -> Tuple[int, int, int]:
        """
        Returns the number of trades in the database broken down by is_my_offer status
        """
        query = "SELECT COUNT(*) AS total, "
        query += "SUM(CASE WHEN is_my_offer=1 THEN 1 ELSE 0 END) AS my_offers, "
        query += "SUM(CASE WHEN is_my_offer=0 THEN 1 ELSE 0 END) AS taken_offers "
        query += "FROM trade_records"

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(query)
            row = await cursor.fetchone()
            await cursor.close()

        total = 0
        my_offers_count = 0
        taken_offers_count = 0

        if row is not None:
            if row[0] is not None:
                total = int(row[0])
            if row[1] is not None:
                my_offers_count = int(row[1])
            if row[2] is not None:
                taken_offers_count = int(row[2])

        return total, my_offers_count, taken_offers_count

    async def get_trade_record(self, trade_id: bytes32) -> Optional[TradeRecord]:
        """
        Checks DB for TradeRecord with id: id and returns it.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT trade_record from trade_records WHERE trade_id=?", (trade_id.hex(),))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            record: TradeRecord = TradeRecord.from_bytes(row[0])
            return record
        return None

    async def get_trade_record_with_status(self, status: TradeStatus) -> List[TradeRecord]:
        """
        Checks DB for TradeRecord with id: id and returns it.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT trade_record from trade_records WHERE status=?", (status.value,))
            rows = await cursor.fetchall()
            await cursor.close()
        records = []
        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_coin_ids_of_interest_with_trade_statuses(self, trade_statuses: List[TradeStatus]) -> Set[bytes32]:
        """
        Checks DB for TradeRecord with id: id and returns it.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT distinct cl.coin_id "
                "from coin_of_interest_to_trade_record cl, trade_records t "
                "WHERE "
                "t.status in (%s) "
                "AND LOWER(hex(cl.trade_id)) = t.trade_id " % (",".join("?" * len(trade_statuses)),),
                [x.value for x in trade_statuses],
            )
        return {bytes32(row[0]) for row in rows}

    async def get_not_sent(self) -> List[TradeRecord]:
        """
        Returns the list of trades that have not been received by full node yet.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT trade_record from trade_records WHERE sent<? and confirmed=?", (4, 0))
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

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT trade_record from trade_records WHERE confirmed=?", (0,))
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

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT trade_record from trade_records")
            rows = await cursor.fetchall()
            await cursor.close()
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

        query = "SELECT trade_record FROM trade_records "
        args = []

        if exclude_my_offers or exclude_taken_offers:
            # We check if exclude_my_offers == exclude_taken_offers earlier and return [] if so
            is_my_offer_val = 0 if exclude_my_offers else 1
            args.append(is_my_offer_val)

            query += "WHERE is_my_offer=? "
            # Include the additional WHERE status clause if we're filtering out certain statuses
            if where_status_clause is not None:
                query += "AND " + where_status_clause
        else:
            query = "SELECT trade_record FROM trade_records "
            # Include the additional WHERE status clause if we're filtering out certain statuses
            if where_status_clause is not None:
                query += "WHERE " + where_status_clause

        # Include the ORDER BY clause
        if order_by_clause is not None:
            query += order_by_clause
        # Include the LIMIT clause
        query += "LIMIT ? OFFSET ?"

        args.extend([limit, offset])

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(query, tuple(args))
            rows = await cursor.fetchall()
            await cursor.close()

        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_trades_above(self, height: uint32) -> List[TradeRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT trade_record from trade_records WHERE confirmed_at_index>?", (height,))
            rows = await cursor.fetchall()
            await cursor.close()
        records = []

        for row in rows:
            record = TradeRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def rollback_to_block(self, block_index: int) -> None:

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Delete from storage
            cursor = await conn.execute("DELETE FROM trade_records WHERE confirmed_at_index>?", (block_index,))
            await cursor.close()
