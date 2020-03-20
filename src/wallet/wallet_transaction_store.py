import asyncio
from typing import Dict, Optional, List
from pathlib import Path
import aiosqlite
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.wallet.transaction_record import TransactionRecord


class WalletTransactionStore:
    """
    WalletTransactionStore stores transaction history for the wallet.
    """

    db_connection: aiosqlite.Connection
    lock: asyncio.Lock
    cache_size: uint32
    tx_record_cache: Dict[bytes32, TransactionRecord]

    @classmethod
    async def create(cls, db_path: Path, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size

        self.db_connection = await aiosqlite.connect(db_path)
        await self.db_connection.execute(
            (
                f"CREATE TABLE IF NOT EXISTS transaction_record("
                f" transaction_record blob,"
                f" bundle_id text PRIMARY KEY,"
                f" confirmed_at_index int,"
                f" created_at_time bigint,"
                f" to_puzzle_hash text,"
                f" amount bigint,"
                f" fee_amount bigint,"
                f" incoming int,"
                f" confirmed int,"
                f" sent int,"
                f" wallet_id int)"
            )
        )

        # Useful for reorg lookups
        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_confirmed_index on transaction_record(confirmed_at_index)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_created_index on transaction_record(created_at_time)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_confirmed on transaction_record(confirmed)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_sent on transaction_record(sent)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_created_time on transaction_record(created_at_time)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_incoming on transaction_record(incoming)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_to_puzzle_hash on transaction_record(to_puzzle_hash)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS wallet_id on transaction_record(wallet_id)"
        )

        await self.db_connection.commit()
        # Lock
        self.lock = asyncio.Lock()  # external
        self.tx_record_cache = dict()
        return self

    async def close(self):
        await self.db_connection.close()

    async def _init_cache(self):
        print("init cache here")

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM transaction_record")
        await cursor.close()
        await self.db_connection.commit()

    async def add_transaction_record(self, record: TransactionRecord) -> None:
        """
        Store TransactionRecord in DB and Cache.
        """

        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO transaction_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bytes(record),
                record.name().hex(),
                record.confirmed_at_index,
                record.created_at_time,
                record.to_puzzle_hash.hex(),
                record.amount,
                record.fee_amount,
                int(record.incoming),
                int(record.confirmed),
                int(record.sent),
                record.wallet_id,
            ),
        )
        await cursor.close()
        await self.db_connection.commit()
        self.tx_record_cache[record.name().hex()] = record
        if len(self.tx_record_cache) > self.cache_size:
            while len(self.tx_record_cache) > self.cache_size:
                first_in = list(self.tx_record_cache.keys())[0]
                self.tx_record_cache.pop(first_in)

    async def set_confirmed(self, id: bytes32, index: uint32):
        """
        Updates transaction to be confirmed.
        """
        current: Optional[TransactionRecord] = await self.get_transaction_record(id)
        if current is None:
            return
        tx: TransactionRecord = TransactionRecord(
            confirmed_at_index=index,
            created_at_time=current.created_at_time,
            to_puzzle_hash=current.to_puzzle_hash,
            amount=current.amount,
            fee_amount=current.fee_amount,
            incoming=current.incoming,
            confirmed=True,
            sent=current.sent,
            spend_bundle=current.spend_bundle,
            additions=current.additions,
            removals=current.removals,
            wallet_id=current.wallet_id,
        )
        await self.add_transaction_record(tx)

    async def unconfirmed_with_removal_coin(
        self, removal_id: bytes32
    ) -> Optional[TransactionRecord]:
        """ Returns a record containing removed coin with id: removal_id"""

        all_unconfirmed: List[TransactionRecord] = await self.get_not_confirmed()
        for record in all_unconfirmed:
            for coin in record.removals:
                if coin.name() == removal_id:
                    return record

        return None

    async def unconfirmed_with_addition_coin(
        self, removal_id: bytes32
    ) -> Optional[TransactionRecord]:
        """ Returns a record containing removed coin with id: removal_id"""

        all_unconfirmed: List[TransactionRecord] = await self.get_not_confirmed()
        for record in all_unconfirmed:
            for coin in record.additions:
                if coin.name() == removal_id:
                    return record

        return None

    async def set_sent(self, id: bytes32):
        """
        Updates transaction to be sent. (Full Node has received spend_bundle and sent ack).
        """

        current: Optional[TransactionRecord] = await self.get_transaction_record(id)
        if current is None:
            return
        tx: TransactionRecord = TransactionRecord(
            confirmed_at_index=current.confirmed_at_index,
            created_at_time=current.created_at_time,
            to_puzzle_hash=current.to_puzzle_hash,
            amount=current.amount,
            fee_amount=current.fee_amount,
            incoming=current.incoming,
            confirmed=current.confirmed,
            sent=True,
            spend_bundle=current.spend_bundle,
            additions=current.additions,
            removals=current.removals,
            wallet_id=current.wallet_id,
        )
        await self.add_transaction_record(tx)

    async def get_transaction_record(self, id: bytes32) -> Optional[TransactionRecord]:
        """
        Checks DB and cache for TransactionRecord with id: id and returns it.
        """

        if id.hex() in self.tx_record_cache:
            return self.tx_record_cache[id.hex()]
        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE bundle_id=?", (id.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            record = TransactionRecord.from_bytes(row[0])
            return record
        return None

    async def get_not_sent(self) -> List[TransactionRecord]:
        """
        Returns the list of transaction that have not been received by full node yet.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE sent=?", (0,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_not_confirmed(self) -> List[TransactionRecord]:
        """
        Returns the list of transaction that have not yet been confirmed.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE confirmed=?", (0,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_all_transactions(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record where wallet_id=?", (wallet_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_transaction_above(self, height: uint32) -> List[TransactionRecord]:
        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE confirmed_at_index>?", (height,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def rollback_to_block(self, block_index):

        # Delete from storage
        c1 = await self.db_connection.execute(
            "DELETE FROM transaction_record WHERE confirmed_at_index>?", (block_index,)
        )
        await c1.close()
        await self.db_connection.commit()
