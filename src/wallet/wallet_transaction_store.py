import asyncio
from typing import Dict, Optional, List, Set
from pathlib import Path
import aiosqlite
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.wallet_types import WalletType


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
                f" transaction_record blob,"
                f" incoming int,"
                f" to_puzzle_hash text,"
                f" amount int,"
                f" fee_amount int)"
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

        await self.transaction_db.execute(
            (
                f"CREATE TABLE IF NOT EXISTS derivation_paths("
                f"id int PRIMARY KEY,"
                f" pubkey text,"
                f" puzzle_hash text,"
                f" wallet_type int,"
                f" used int)"
            )
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS ph on derivation_paths(puzzle_hash)"
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS pubkey on derivation_paths(pubkey)"
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS wallet_type on derivation_paths(wallet_type)"
        )

        await self.transaction_db.execute(
            "CREATE INDEX IF NOT EXISTS used on derivation_paths(wallet_type)"
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
            "INSERT OR REPLACE INTO transaction_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.name().hex(),
                record.confirmed_block_index,
                record.created_at_index,
                int(record.confirmed),
                int(record.sent),
                record.created_at_time,
                bytes(record),
                int(record.incoming),
                record.to_puzzle_hash.hex(),
                record.amount,
                record.fee_amount,
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
            current.incoming,
            current.to_puzzle_hash,
            current.amount,
            current.fee_amount,
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
            current.incoming,
            current.to_puzzle_hash,
            current.amount,
            current.fee_amount,
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

    async def add_derivation_path_of_interest(
        self, index: int, puzzlehash: bytes32, pubkey: bytes, wallet_type: WalletType
    ):
        cursor = await self.transaction_db.execute(
            "INSERT OR REPLACE INTO derivation_paths VALUES(?, ?, ?, ?, ?)",
            (index, pubkey.hex(), puzzlehash.hex(), wallet_type.value, 0),
        )

        await cursor.close()
        await self.transaction_db.commit()

    async def puzzle_hash_exists(self, puzzle_hash: bytes32) -> bool:
        cursor = await self.transaction_db.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()
        await cursor.close()

        if len(list(rows)) > 0:
            return True

        return False

    async def index_for_pubkey(self, pubkey: str) -> int:
        cursor = await self.transaction_db.execute(
            "SELECT * from derivation_paths WHERE pubkey=?", (pubkey,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return row[0]

        return -1

    async def index_for_puzzle_hash(self, pubkey: bytes32) -> int:
        cursor = await self.transaction_db.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (pubkey.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return row[0]

        return -1

    async def get_all_puzzle_hashes(self) -> Set[bytes32]:
        """ Return a set containing all puzzle_hashes we generated. """
        cursor = await self.transaction_db.execute("SELECT * from derivation_paths")
        rows = await cursor.fetchall()
        await cursor.close()
        result: Set[bytes32] = set()

        for row in rows:
            result.add(row[2])

        return result

    async def get_max_derivation_path(self):
        cursor = await self.transaction_db.execute(
            "SELECT MAX(id) FROM derivation_paths;"
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row[0]:
            return row[0]

        return 0
