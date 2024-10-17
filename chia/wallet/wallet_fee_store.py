from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32
from chia.wallet.fee_record import FeeRecord, FeeRecordKey

"""
FPC is "Fee per Cost". This is similar to Bitcoin's fee per byte, but our transaction cost metric is different.
Fees are in mojos
Fee rates (for a single transaction or the whole mempool) are in mojos per FPC

A typical Chia transaction (Send from a single XCH coin, producing a new XCH coin, and a change coin)
costs STANDARD_TX_COST mojos


"""

MINUTES_IN_WEEK = 1440 * 7 * 60  # Approximate number of entries to keep
SECONDS_IN_WEEK = MINUTES_IN_WEEK * 60
STANDARD_TX_COST = 10632842
MEMPOOL_CONSIDERED_FULL_RATIO = 0.8


class FeeStore:
    """
    Remember things relevant to fees for the Wallet. Mostly Mempool state.
    """

    max_cache_size: uint32
    db_wrapper: DBWrapper2
    log: logging.Logger

    @classmethod
    async def create(
        cls, db_wrapper: DBWrapper2, max_cache_size: uint32 = uint32(MINUTES_IN_WEEK), name: Optional[str] = None
    ) -> FeeStore:
        self = cls()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.max_cache_size = max_cache_size
        self.db_wrapper = db_wrapper

        # REVIEW: Should we use two tables: one for mempool data, one for estimates?
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS fee_records("
                " block_hash text,"  # block_hash is stored as bytes, not hex
                " estimator_name text,"
                " estimator_version tinyint,"
                " fee_record blob,"
                " block_index int,"
                " block_time bigint,"
                " block_fpc  int,"  #
                " fpc_to_add_std_tx int,"  # mojos
                " estimated_fpc_numerator int,"
                " estimated_fpc_denominator int,"
                " primary key (block_hash, estimator_name, estimator_version)"
                ")"
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS block_hash on fee_records(block_hash)")
            await conn.execute("CREATE INDEX IF NOT EXISTS block_index on fee_records(block_index)")
            await conn.execute("CREATE INDEX IF NOT EXISTS block_time on fee_records(block_time)")

        return self

    async def add_fee_record(self, key: FeeRecordKey, rec: FeeRecord, *, replace: bool = False) -> None:
        """
        Store FeeRecord into DB. This happens once per transaction block.
        """
        # if record.block_hash
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            if not replace:
                existing_entries_with_same_block_hash = await self.get_fee_record(key)
                if existing_entries_with_same_block_hash:
                    raise ValueError(f"FeeRecord for {key} already exists. Not replacing.")
            cursor = await conn.execute(
                f"INSERT OR REPLACE INTO fee_records " f"({', '.join(FeeRecord.columns)}) " f"VALUES(?, ?, ?, ?, ?, ?)",
                (
                    key.block_hash,  # block_hash stored as bytes, not hex
                    key.estimator_name,
                    key.estimator_version,
                    bytes(rec),
                    rec.block_index,
                    rec.block_time,
                ),
            )
            await cursor.close()

    @classmethod
    def _row_to_fee_record(cls, row: sqlite3.Row) -> FeeRecord:
        return FeeRecord.from_bytes(row[0])  # cast: mypy limitation

    async def get_fee_record(self, key: FeeRecordKey) -> Optional[FeeRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            conn.row_factory = sqlite3.Row
            cursor = await conn.execute(
                "SELECT fee_record from fee_records WHERE block_hash=? AND estimator_name=? AND estimator_version=?",
                (key.block_hash, key.estimator_name, key.estimator_version),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:

            return self._row_to_fee_record(row)
        logging.getLogger(__name__).error(f"Dumping whole DB: {str()}")
        return None

    async def get_fee_record2(self, key: FeeRecordKey) -> Optional[FeeRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            conn.row_factory = sqlite3.Row
            cursor = await conn.execute(
                "SELECT fee_record from fee_records WHERE block_hash=? AND estimator_name=? AND estimator_version=?",
                (key.block_hash, key.estimator_name, key.estimator_version),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return self._row_to_fee_record(row)
        logging.getLogger(__name__).error(f"Dumping whole DB: {str()}")
        return None

    async def rollback_to_block(self, block_index: int) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Delete from storage
            cursor = await conn.execute("DELETE FROM fee_records WHERE block_index>?", (block_index,))
            await cursor.close()

    async def prune(self) -> None:
        """Delete records older than SECONDS_IN_WEEK"""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            now_secs = time.time()
            cursor = await conn.execute("DELETE FROM fee_records WHERE block_time<?", (now_secs - SECONDS_IN_WEEK,))
            await cursor.close()
