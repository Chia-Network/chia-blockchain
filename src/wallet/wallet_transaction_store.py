import asyncio
from typing import Dict, Optional, List
from pathlib import Path
import aiosqlite
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.wallet.transaction_record import TransactionRecord


class WalletTransactionStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    transaction_db: aiosqlite.Connection
    # Whether or not we are syncing
    sync_mode: bool = False
    lock: asyncio.Lock
    cache_size: uint32
    tx_record_cache: Dict[bytes32, TransactionRecord]

    @classmethod
    async def create(cls, db_path: Path, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size

        self.transaction_db = await aiosqlite.connect(db_path)
        await self.transaction_db.execute(
            (
                f"CREATE TABLE IF NOT EXISTS transaction_record("
                f"bundle_id text PRIMARY KEY,"
                f" confirmed_index bigint,"
                f" created_at_index bigint,"
                f" confirmed int,"
                f" sent int,"
                f" created_at_time bigint,"
                f" transaction_record blob)"
            )
        )

        # Useful for reorg lookups
        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS tx_confirmed_index on transaction_record(confirmed_index)"
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS tx_created_index on transaction_record(created_at_index)"
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS tx_confirmed on transaction_record(confirmed)"
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS tx_sent on transaction_record(sent)"
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS tx_created_time on transaction_record(created_at_time)"
        )

        await self.transaction_db.commit()
        # Lock
        self.lock = asyncio.Lock()  # external
        self.tx_record_cache = dict()
        return self

    async def close(self):
        await self.transaction_db.close()

    async def _init_cache(self):
        print("init cache here")

    async def _clear_database(self):
        cursor = await self.transaction_db.execute("DELETE FROM transaction_record")
        await cursor.close()
        await self.transaction_db.commit()

    # Store TransactionRecord in DB and Cache
    async def add_transaction_record(self, record: TransactionRecord) -> None:
        cursor = await self.transaction_db.execute(
            "INSERT OR REPLACE INTO transaction_record VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                record.name().hex(),
                record.confirmed_block_index,
                record.created_at_index,
                int(record.confirmed),
                int(record.sent),
                record.created_at_time,
                bytes(record),
            ),
        )
        await cursor.close()
        await self.transaction_db.commit()
        self.tx_record_cache[record.name().hex()] = record
        if len(self.tx_record_cache) > self.cache_size:
            while len(self.tx_record_cache) > self.cache_size:
                first_in = list(self.tx_record_cache.keys())[0]
                self.tx_record_cache.pop(first_in)

    # Update transaction_record to be confirmed in DB
    async def set_confirmed(self, id: bytes32, index: uint32):
        current: Optional[TransactionRecord] = await self.get_transaction_record(id)
        if current is None:
            return
        tx: TransactionRecord = TransactionRecord(
            index,
            current.created_at_index,
            True,
            current.sent,
            current.created_at_time,
            current.spend_bundle,
            current.additions,
            current.removals,
        )
        await self.add_transaction_record(tx)

    # Update transaction_record to be sent in DB
    async def set_sent(self, id: bytes32):
        current: Optional[TransactionRecord] = await self.get_transaction_record(id)
        if current is None:
            return
        tx: TransactionRecord = TransactionRecord(
            current.confirmed_block_index,
            current.created_at_index,
            current.confirmed,
            True,
            current.created_at_time,
            current.spend_bundle,
            current.additions,
            current.removals,
        )
        await self.add_transaction_record(tx)

    # Checks DB and cache for TransactionRecord with id: id and returns it
    async def get_transaction_record(self, id: bytes32) -> Optional[TransactionRecord]:
        if id.hex() in self.tx_record_cache:
            return self.tx_record_cache[id.hex()]
        cursor = await self.transaction_db.execute(
            "SELECT * from transaction_record WHERE bundle_id=?", (id.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            record = TransactionRecord.from_bytes(row[6])
            return record
        return None

    async def get_not_sent(self) -> List[TransactionRecord]:
        cursor = await self.transaction_db.execute(
            "SELECT * from transaction_record WHERE sent=?", (0,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TransactionRecord.from_bytes(row[6])
            records.append(record)

        return records

    async def get_not_confirmed(self) -> List[TransactionRecord]:
        cursor = await self.transaction_db.execute(
            "SELECT * from transaction_record WHERE confirmed=?", (0,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TransactionRecord.from_bytes(row[6])
            records.append(record)

        return records

    async def get_all_transactions(self) -> List[TransactionRecord]:
        cursor = await self.transaction_db.execute("SELECT * from transaction_record")
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TransactionRecord.from_bytes(row[6])
            records.append(record)

        return records
