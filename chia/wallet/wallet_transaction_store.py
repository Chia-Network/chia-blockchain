import time
from typing import Dict, List, Optional, Tuple

import aiosqlite

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.db_wrapper import DBWrapper
from chia.util.errors import Err
from chia.util.ints import uint8, uint32
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType


class WalletTransactionStore:
    """
    WalletTransactionStore stores transaction history for the wallet.
    """

    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper
    tx_record_cache: Dict[bytes32, TransactionRecord]
    tx_submitted: Dict[bytes32, Tuple[int, int]]  # tx_id: [time submitted: count]
    unconfirmed_for_wallet: Dict[int, Dict[bytes32, TransactionRecord]]

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        self.db_wrapper = db_wrapper
        self.db_connection = self.db_wrapper.db
        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS transaction_record("
                " transaction_record blob,"
                " bundle_id text PRIMARY KEY,"  # NOTE: bundle_id is being stored as bytes, not hex
                " confirmed_at_height bigint,"
                " created_at_time bigint,"
                " to_puzzle_hash text,"
                " amount blob,"
                " fee_amount blob,"
                " confirmed int,"
                " sent int,"
                " wallet_id bigint,"
                " trade_id text,"
                " type int)"
            )
        )

        # Useful for reorg lookups
        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_confirmed_index on transaction_record(confirmed_at_height)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_created_index on transaction_record(created_at_time)"
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS tx_confirmed on transaction_record(confirmed)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS tx_sent on transaction_record(sent)")

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_created_time on transaction_record(created_at_time)"
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS tx_type on transaction_record(type)")

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_to_puzzle_hash on transaction_record(to_puzzle_hash)"
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS wallet_id on transaction_record(wallet_id)")

        await self.db_connection.commit()
        self.tx_record_cache = {}
        self.tx_submitted = {}
        self.unconfirmed_for_wallet = {}
        await self.rebuild_tx_cache()
        return self

    async def rebuild_tx_cache(self):
        # init cache here
        all_records = await self.get_all_transactions()
        self.tx_record_cache = {}
        self.unconfirmed_for_wallet = {}

        for record in all_records:
            self.tx_record_cache[record.name] = record
            if record.wallet_id not in self.unconfirmed_for_wallet:
                self.unconfirmed_for_wallet[record.wallet_id] = {}
            if not record.confirmed:
                self.unconfirmed_for_wallet[record.wallet_id][record.name] = record

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM transaction_record")
        await cursor.close()
        await self.db_connection.commit()

    async def add_transaction_record(self, record: TransactionRecord, in_transaction: bool) -> None:
        """
        Store TransactionRecord in DB and Cache.
        """
        self.tx_record_cache[record.name] = record
        if record.wallet_id not in self.unconfirmed_for_wallet:
            self.unconfirmed_for_wallet[record.wallet_id] = {}
        unconfirmed_dict = self.unconfirmed_for_wallet[record.wallet_id]
        if record.confirmed and record.name in unconfirmed_dict:
            unconfirmed_dict.pop(record.name)
        if not record.confirmed:
            unconfirmed_dict[record.name] = record

        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute(
                "INSERT OR REPLACE INTO transaction_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bytes(record),
                    record.name,
                    record.confirmed_at_height,
                    record.created_at_time,
                    record.to_puzzle_hash.hex(),
                    bytes(record.amount),
                    bytes(record.fee_amount),
                    int(record.confirmed),
                    record.sent,
                    record.wallet_id,
                    record.trade_id,
                    record.type,
                ),
            )
            await cursor.close()
            if not in_transaction:
                await self.db_connection.commit()
        except BaseException:
            if not in_transaction:
                await self.rebuild_tx_cache()
            raise
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def set_confirmed(self, tx_id: bytes32, height: uint32):
        """
        Updates transaction to be confirmed.
        """
        current: Optional[TransactionRecord] = await self.get_transaction_record(tx_id)
        if current is None:
            return None
        if current.confirmed_at_height == height:
            return
        tx: TransactionRecord = TransactionRecord(
            confirmed_at_height=height,
            created_at_time=current.created_at_time,
            to_puzzle_hash=current.to_puzzle_hash,
            amount=current.amount,
            fee_amount=current.fee_amount,
            confirmed=True,
            sent=current.sent,
            spend_bundle=current.spend_bundle,
            additions=current.additions,
            removals=current.removals,
            wallet_id=current.wallet_id,
            sent_to=current.sent_to,
            trade_id=None,
            type=current.type,
            name=current.name,
        )
        await self.add_transaction_record(tx, True)

    async def increment_sent(
        self,
        tx_id: bytes32,
        name: str,
        send_status: MempoolInclusionStatus,
        err: Optional[Err],
    ) -> bool:
        """
        Updates transaction sent count (Full Node has received spend_bundle and sent ack).
        """

        current: Optional[TransactionRecord] = await self.get_transaction_record(tx_id)
        if current is None:
            return False

        sent_to = current.sent_to.copy()

        current_peers = set()
        err_str = err.name if err is not None else None
        append_data = (name, uint8(send_status.value), err_str)

        for peer_id, status, error in sent_to:
            current_peers.add(peer_id)

        if name in current_peers:
            sent_count = uint32(current.sent)
        else:
            sent_count = uint32(current.sent + 1)

        sent_to.append(append_data)

        tx: TransactionRecord = TransactionRecord(
            confirmed_at_height=current.confirmed_at_height,
            created_at_time=current.created_at_time,
            to_puzzle_hash=current.to_puzzle_hash,
            amount=current.amount,
            fee_amount=current.fee_amount,
            confirmed=current.confirmed,
            sent=sent_count,
            spend_bundle=current.spend_bundle,
            additions=current.additions,
            removals=current.removals,
            wallet_id=current.wallet_id,
            sent_to=sent_to,
            trade_id=None,
            type=current.type,
            name=current.name,
        )

        await self.add_transaction_record(tx, False)
        return True

    async def tx_reorged(self, record: TransactionRecord):
        """
        Updates transaction sent count to 0 and resets confirmation data
        """
        tx: TransactionRecord = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=record.created_at_time,
            to_puzzle_hash=record.to_puzzle_hash,
            amount=record.amount,
            fee_amount=record.fee_amount,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=record.spend_bundle,
            additions=record.additions,
            removals=record.removals,
            wallet_id=record.wallet_id,
            sent_to=[],
            trade_id=None,
            type=record.type,
            name=record.name,
        )
        await self.add_transaction_record(tx, True)

    async def get_transaction_record(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        """
        Checks DB and cache for TransactionRecord with id: id and returns it.
        """
        if tx_id in self.tx_record_cache:
            return self.tx_record_cache[tx_id]

        # NOTE: bundle_id is being stored as bytes, not hex
        cursor = await self.db_connection.execute("SELECT * from transaction_record WHERE bundle_id=?", (tx_id,))
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
        current_time = int(time.time())
        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE confirmed=?",
            (0,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            if record.name in self.tx_submitted:
                time_submitted, count = self.tx_submitted[record.name]
                if time_submitted < current_time - (60 * 10):
                    records.append(record)
                    self.tx_submitted[record.name] = current_time, 1
                else:
                    if count < 5:
                        records.append(record)
                        self.tx_submitted[record.name] = time_submitted, (count + 1)
            else:
                records.append(record)
                self.tx_submitted[record.name] = current_time, 1

        return records

    async def get_farming_rewards(self) -> List[TransactionRecord]:
        """
        Returns the list of all farming rewards.
        """
        fee_int = TransactionType.FEE_REWARD.value
        pool_int = TransactionType.COINBASE_REWARD.value
        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE confirmed=? and (type=? or type=?)", (1, fee_int, pool_int)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_all_unconfirmed(self) -> List[TransactionRecord]:
        """
        Returns the list of all transaction that have not yet been confirmed.
        """

        cursor = await self.db_connection.execute("SELECT * from transaction_record WHERE confirmed=?", (0,))
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_unconfirmed_for_wallet(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Returns the list of transaction that have not yet been confirmed.
        """
        if wallet_id in self.unconfirmed_for_wallet:
            return list(self.unconfirmed_for_wallet[wallet_id].values())
        else:
            return []

    async def get_transactions_between(self, wallet_id: int, start, end) -> List[TransactionRecord]:
        """Return a list of transaction between start and end index. List is in reverse chronological order.
        start = 0 is most recent transaction
        """
        limit = end - start
        cursor = await self.db_connection.execute(
            f"SELECT * from transaction_record where wallet_id=? and confirmed_at_height not in"
            f" (select confirmed_at_height from transaction_record order by confirmed_at_height"
            f" ASC LIMIT {start})"
            f" order by confirmed_at_height DESC LIMIT {limit}",
            (wallet_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        records.reverse()

        return records

    async def get_transaction_count_for_wallet(self, wallet_id) -> int:
        cursor = await self.db_connection.execute(
            "SELECT COUNT(*) FROM transaction_record where wallet_id=?", (wallet_id,)
        )
        count_result = await cursor.fetchone()
        if count_result is not None:
            count = count_result[0]
        else:
            count = 0
        await cursor.close()
        return count

    async def get_all_transactions_for_wallet(self, wallet_id: int, type: int = None) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """
        if type is None:
            cursor = await self.db_connection.execute(
                "SELECT * from transaction_record where wallet_id=?", (wallet_id,)
            )
        else:
            cursor = await self.db_connection.execute(
                "SELECT * from transaction_record where wallet_id=? and type=?",
                (
                    wallet_id,
                    type,
                ),
            )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        cache_set = set()
        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)
            cache_set.add(record.name)

        return records

    async def get_all_transactions(self) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """
        cursor = await self.db_connection.execute("SELECT * from transaction_record")
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_transaction_above(self, height: int) -> List[TransactionRecord]:
        # Can be -1 (get all tx)

        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE confirmed_at_height>?", (height,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def rollback_to_block(self, height: int):
        # Delete from storage
        to_delete = []
        for tx in self.tx_record_cache.values():
            if tx.confirmed_at_height > height:
                to_delete.append(tx)
        for tx in to_delete:
            self.tx_record_cache.pop(tx.name)

        c1 = await self.db_connection.execute("DELETE FROM transaction_record WHERE confirmed_at_height>?", (height,))
        await c1.close()

    async def delete_unconfirmed_transactions(self, wallet_id: int):
        cursor = await self.db_connection.execute(
            "DELETE FROM transaction_record WHERE confirmed=0 AND wallet_id=?", (wallet_id,)
        )
        await cursor.close()
