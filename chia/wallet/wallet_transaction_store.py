import dataclasses
import time
from typing import Dict, List, Optional, Tuple

import aiosqlite

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.db_wrapper import DBWrapper
from chia.util.errors import Err
from chia.util.ints import uint8, uint32
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.transaction_type import TransactionType


def filter_ok_mempool_status(sent_to: List[Tuple[str, uint8, Optional[str]]]) -> List[Tuple[str, uint8, Optional[str]]]:
    """Remove SUCCESS and PENDING status records from a TransactionRecord sent_to field"""
    new_sent_to = []
    for peer, status, err in sent_to:
        if status == MempoolInclusionStatus.FAILED.value:
            new_sent_to.append((peer, status, err))
    return new_sent_to


class WalletTransactionStore:
    """
    WalletTransactionStore stores transaction history for the wallet.
    """

    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper
    tx_submitted: Dict[bytes32, Tuple[int, int]]  # tx_id: [time submitted: count]
    last_wallet_tx_resend_time: int  # Epoch time in seconds

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

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS transaction_record_wallet_id on transaction_record(wallet_id)"
        )

        await self.db_connection.commit()
        self.tx_submitted = {}
        self.last_wallet_tx_resend_time = int(time.time())
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM transaction_record")
        await cursor.close()
        await self.db_connection.commit()

    async def add_transaction_record(self, record: TransactionRecord, in_transaction: bool) -> None:
        """
        Store TransactionRecord in DB and Cache.
        """
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            await self.db_connection.execute_insert(
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
            if not in_transaction:
                await self.db_connection.commit()
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def delete_transaction_record(self, tx_id: bytes32) -> None:
        c = await self.db_connection.execute("DELETE FROM transaction_record WHERE bundle_id=?", (tx_id,))
        await c.close()

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
            trade_id=current.trade_id,
            type=current.type,
            name=current.name,
            memos=current.memos,
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
            trade_id=current.trade_id,
            type=current.type,
            name=current.name,
            memos=current.memos,
        )

        await self.add_transaction_record(tx, False)
        return True

    async def tx_reorged(self, record: TransactionRecord, in_transaction: bool) -> None:
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
            trade_id=record.trade_id,
            type=record.type,
            name=record.name,
            memos=record.memos,
        )
        await self.add_transaction_record(tx, in_transaction=in_transaction)

    async def get_transaction_record(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        """
        Checks DB and cache for TransactionRecord with id: id and returns it.
        """
        # NOTE: bundle_id is being stored as bytes, not hex
        rows = list(
            await self.db_connection.execute_fetchall("SELECT * from transaction_record WHERE bundle_id=?", (tx_id,))
        )
        if len(rows) > 0:
            return TransactionRecord.from_bytes(rows[0][0])
        return None

    # TODO: This should probably be split into separate function, one that
    # queries the state and one that updates it. Also, include_accepted_txs=True
    # might be a separate function too.
    # also, the current time should be passed in as a paramter
    async def get_not_sent(self, *, include_accepted_txs=False) -> List[TransactionRecord]:
        """
        Returns the list of transactions that have not been received by full node yet.
        """
        current_time = int(time.time())
        rows = await self.db_connection.execute_fetchall(
            "SELECT * from transaction_record WHERE confirmed=0",
        )
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            if include_accepted_txs:
                # Reset the "sent" state for peers that have replied about this transaction. Retain errors.
                record = dataclasses.replace(record, sent=1, sent_to=filter_ok_mempool_status(record.sent_to))
                await self.add_transaction_record(record, False)
                self.tx_submitted[record.name] = current_time, 1
                records.append(record)
            elif record.name in self.tx_submitted:
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
        rows = await self.db_connection.execute_fetchall(
            "SELECT * from transaction_record WHERE confirmed=1 and (type=? or type=?)", (fee_int, pool_int)
        )
        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def get_all_unconfirmed(self) -> List[TransactionRecord]:
        """
        Returns the list of all transaction that have not yet been confirmed.
        """

        rows = await self.db_connection.execute_fetchall("SELECT * from transaction_record WHERE confirmed=0")
        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def get_unconfirmed_for_wallet(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Returns the list of transaction that have not yet been confirmed.
        """
        rows = await self.db_connection.execute_fetchall(
            "SELECT transaction_record from transaction_record WHERE confirmed=0 AND wallet_id=?", (wallet_id,)
        )
        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def get_transactions_between(
        self, wallet_id: int, start, end, sort_key=None, reverse=False, to_puzzle_hash: Optional[bytes32] = None
    ) -> List[TransactionRecord]:
        """Return a list of transaction between start and end index. List is in reverse chronological order.
        start = 0 is most recent transaction
        """
        limit = end - start

        if to_puzzle_hash is None:
            puzz_hash_where = ""
        else:
            puzz_hash_where = f' AND to_puzzle_hash="{to_puzzle_hash.hex()}"'

        if sort_key is None:
            sort_key = "CONFIRMED_AT_HEIGHT"
        if sort_key not in SortKey.__members__:
            raise ValueError(f"There is no known sort {sort_key}")

        if reverse:
            query_str = SortKey[sort_key].descending()
        else:
            query_str = SortKey[sort_key].ascending()

        rows = await self.db_connection.execute_fetchall(
            f"SELECT * from transaction_record WHERE wallet_id=?{puzz_hash_where}"
            f" {query_str}, rowid"
            f" LIMIT {start}, {limit}",
            (wallet_id,),
        )

        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def get_transaction_count_for_wallet(self, wallet_id) -> int:
        rows = list(
            await self.db_connection.execute_fetchall(
                "SELECT COUNT(*) FROM transaction_record where wallet_id=?", (wallet_id,)
            )
        )
        return 0 if len(rows) == 0 else rows[0][0]

    async def get_all_transactions_for_wallet(self, wallet_id: int, type: int = None) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """
        if type is None:
            rows = await self.db_connection.execute_fetchall(
                "SELECT * FROM transaction_record WHERE wallet_id=?", (wallet_id,)
            )
        else:
            rows = await self.db_connection.execute_fetchall(
                "SELECT * FROM transaction_record WHERE wallet_id=? AND type=?",
                (
                    wallet_id,
                    type,
                ),
            )
        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def get_all_transactions(self) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """
        rows = await self.db_connection.execute_fetchall("SELECT * from transaction_record")
        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def get_transaction_above(self, height: int) -> List[TransactionRecord]:
        # Can be -1 (get all tx)

        rows = await self.db_connection.execute_fetchall(
            "SELECT * from transaction_record WHERE confirmed_at_height>?", (height,)
        )
        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def get_transactions_by_trade_id(self, trade_id: bytes32) -> List[TransactionRecord]:
        rows = await self.db_connection.execute_fetchall(
            "SELECT * from transaction_record WHERE trade_id=?", (trade_id,)
        )
        return [TransactionRecord.from_bytes(row[0]) for row in rows]

    async def rollback_to_block(self, height: int):
        # Delete from storage
        self.tx_submitted = {}
        c1 = await self.db_connection.execute("DELETE FROM transaction_record WHERE confirmed_at_height>?", (height,))
        await c1.close()

    async def delete_unconfirmed_transactions(self, wallet_id: int):
        cursor = await self.db_connection.execute(
            "DELETE FROM transaction_record WHERE confirmed=0 AND wallet_id=?", (wallet_id,)
        )
        await cursor.close()
