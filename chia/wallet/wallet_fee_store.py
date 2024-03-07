from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint8, uint32
from chia.wallet.fee_record import FeeRecord

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

# Note: See class CostLogger


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

        # REVIEW: Use two tables: one for mempool data, one for estimates?
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # REVIEW: Rather than a composite key, would it be better to use an int
            #         primary key, and guarantee unique for estimate_type & estimate_version
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS fee_records("
                " fee_record blob,"
                " block_hash text,"  # block_hash stored as bytes, not hex
                " block_index int,"
                " block_time bigint,"
                " block_fpc  int,"  # total mojos in fees divided by total clvm_cost
                " fpc_to_add_std_tx int,"  # mojos
                " estimated_fpc_numerator int,"
                " estimated_fpc_denominator int,"
                " estimate_type text,"
                " estimate_version tinyint,"
                " primary key (block_hash, estimate_type, estimate_version)"
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS block_hash on fee_records(block_hash)")
            await conn.execute("CREATE INDEX IF NOT EXISTS block_index on fee_records(block_index)")
            await conn.execute("CREATE INDEX IF NOT EXISTS block_time on fee_records(block_time)")

        return self

    async def add_fee_record(self, rec: FeeRecord, block_hash: bytes32, *, replace: bool = False) -> None:
        """
        Store FeeRecord into DB. This happens once per transaction block.
        """
        # if record.block_hash
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            if not replace:
                # existing_entries_with_same_block_hash = await conn.execute_fetchall(
                #     "SELECT block_hash FROM fee_records WHERE block_hash=? LIMIT 1",
                #     (block_hash,),
                # )
                existing_entries_with_same_block_hash = await self.get_fee_record(
                    block_hash, rec.estimate_type, rec.estimate_version
                )
                if existing_entries_with_same_block_hash:
                    raise ValueError("FeeRecord for block {} already exists. Not replacing")
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO fee_records "
                "(fee_record, block_hash, block_time, block_index, created_at_time, ) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bytes(rec),
                    # block_hash,  # block_hash stored as bytes, not hex
                    rec.block_index,
                    rec.block_time,
                    rec.block_fpc,
                    rec.fpc_to_add_std_tx,
                    rec.estimated_fpc,
                    rec.estimate_type,
                    rec.estimate_version,
                ),
            )
            await cursor.close()

    @classmethod
    def _row_to_fee_record(cls, row: sqlite3.Row) -> FeeRecord:
        return FeeRecord(**{k: row[k] for k in row.keys()})

    # Note: front-end might need "async def get_between_blocks(a, b)" or "get_last_n"
    async def get_fee_record(self, block_hash: bytes32, est_type: str, est_ver: uint8) -> Optional[FeeRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT fee_record from fee_records WHERE block_hash=? AND estimate_type=? AND estimate_version=?",
                (block_hash, est_type, est_ver),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return self._row_to_fee_record(row)
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
