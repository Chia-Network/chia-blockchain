from __future__ import annotations

import dataclasses
import logging
import time
from typing import Dict, List, Optional, Tuple

import aiosqlite

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.db_wrapper import DBWrapper2
from chia.util.errors import Err
from chia.util.ints import uint8, uint32
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord, TransactionRecordOld, minimum_send_attempts
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.query_filter import FilterMode, TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType

log = logging.getLogger(__name__)


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

    db_wrapper: DBWrapper2
    tx_submitted: Dict[bytes32, Tuple[int, int]]  # tx_id: [time submitted: count]
    last_wallet_tx_resend_time: int  # Epoch time in seconds

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2):
        self = cls()

        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
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

            # Useful for reorg lookups
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS tx_confirmed_index on transaction_record(confirmed_at_height)"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS tx_created_index on transaction_record(created_at_time)")
            # Remove a redundant index on `created_at_time`
            # See https://github.com/Chia-Network/chia-blockchain/issues/10276
            await conn.execute("DROP INDEX IF EXISTS tx_created_time")
            await conn.execute("CREATE INDEX IF NOT EXISTS tx_to_puzzle_hash on transaction_record(to_puzzle_hash)")
            await conn.execute("CREATE INDEX IF NOT EXISTS tx_confirmed on transaction_record(confirmed)")
            await conn.execute("CREATE INDEX IF NOT EXISTS tx_sent on transaction_record(sent)")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS transaction_record_wallet_id on transaction_record(wallet_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS transaction_record_trade_id_idx ON transaction_record(trade_id)"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS tx_type on transaction_record(type)")

            try:
                await conn.execute("CREATE TABLE tx_times(txid blob PRIMARY KEY, valid_times blob)")
                async with await conn.execute("SELECT bundle_id from transaction_record") as cursor:
                    txids: List[bytes32] = [bytes32(row[0]) for row in await cursor.fetchall()]
                    await conn.executemany(
                        "INSERT INTO tx_times (txid, valid_times) VALUES(?, ?)",
                        [(id, bytes(ConditionValidTimes())) for id in txids],
                    )
            except aiosqlite.OperationalError:
                pass  # ignore what is likely Duplicate table error

        self.tx_submitted = {}
        self.last_wallet_tx_resend_time = int(time.time())
        return self

    async def add_transaction_record(self, record: TransactionRecord) -> None:
        """
        Store TransactionRecord in DB and Cache.
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            transaction_record_old = TransactionRecordOld(
                confirmed_at_height=record.confirmed_at_height,
                created_at_time=record.created_at_time,
                to_puzzle_hash=record.to_puzzle_hash,
                amount=record.amount,
                fee_amount=record.fee_amount,
                confirmed=record.confirmed,
                sent=record.sent,
                spend_bundle=record.spend_bundle,
                additions=record.additions,
                removals=record.removals,
                wallet_id=record.wallet_id,
                sent_to=record.sent_to,
                trade_id=record.trade_id,
                type=record.type,
                name=record.name,
                memos=record.memos,
            )
            await conn.execute_insert(
                "INSERT OR REPLACE INTO transaction_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bytes(transaction_record_old),
                    record.name,
                    record.confirmed_at_height,
                    record.created_at_time,
                    record.to_puzzle_hash.hex(),
                    record.amount.stream_to_bytes(),
                    record.fee_amount.stream_to_bytes(),
                    int(record.confirmed),
                    record.sent,
                    record.wallet_id,
                    record.trade_id,
                    record.type,
                ),
            )
            await conn.execute_insert(
                "INSERT OR REPLACE INTO tx_times VALUES (?, ?)", (record.name, bytes(record.valid_times))
            )

    async def delete_transaction_record(self, tx_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM transaction_record WHERE bundle_id=?", (tx_id,))).close()

    async def set_confirmed(self, tx_id: bytes32, height: uint32):
        """
        Updates transaction to be confirmed.
        """
        current: Optional[TransactionRecord] = await self.get_transaction_record(tx_id)
        if current is None:
            return None
        if current.confirmed_at_height == height:
            return
        tx: TransactionRecord = dataclasses.replace(current, confirmed_at_height=height, confirmed=True)
        await self.add_transaction_record(tx)

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

        tx: TransactionRecord = dataclasses.replace(current, sent=sent_count, sent_to=sent_to)
        if not tx.is_valid():
            # if the tx is not valid due to repeated failures, we will confirm that we can't spend it
            log.info(f"Marking tx={tx.name} as confirmed but failed, since it is not spendable due to errors")
            tx = dataclasses.replace(tx, confirmed=True, confirmed_at_height=uint32(0))
        await self.add_transaction_record(tx)
        return True

    async def tx_reorged(self, record: TransactionRecord):
        """
        Updates transaction sent count to 0 and resets confirmation data
        """
        tx: TransactionRecord = dataclasses.replace(
            record, confirmed_at_height=uint32(0), confirmed=False, sent=uint32(0), sent_to=[]
        )
        await self.add_transaction_record(tx)

    async def get_transaction_record(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        """
        Checks DB and cache for TransactionRecord with id: id and returns it.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            # NOTE: bundle_id is being stored as bytes, not hex
            rows = list(
                await conn.execute_fetchall(
                    "SELECT transaction_record from transaction_record WHERE bundle_id=?", (tx_id,)
                )
            )
        if len(rows) > 0:
            return (await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(rows[0][0])]))[0]
        return None

    # TODO: This should probably be split into separate function, one that
    # queries the state and one that updates it. Also, include_accepted_txs=True
    # might be a separate function too.
    # also, the current time should be passed in as a parameter
    async def get_not_sent(self, *, include_accepted_txs=False) -> List[TransactionRecord]:
        """
        Returns the list of transactions that have not been received by full node yet.
        """
        current_time = int(time.time())
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT transaction_record from transaction_record WHERE confirmed=0",
            )
        records = []

        for row in rows:
            record = (await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0])]))[0]
            if include_accepted_txs:
                # Reset the "sent" state for peers that have replied about this transaction. Retain errors.
                record = dataclasses.replace(record, sent=uint32(1), sent_to=filter_ok_mempool_status(record.sent_to))
                await self.add_transaction_record(record)
                self.tx_submitted[record.name] = current_time, 1
                records.append(record)
            elif record.name in self.tx_submitted:
                time_submitted, count = self.tx_submitted[record.name]
                if time_submitted < current_time - (60 * 10):
                    records.append(record)
                    self.tx_submitted[record.name] = current_time, 1
                else:
                    if count < minimum_send_attempts:
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
        async with self.db_wrapper.reader_no_transaction() as conn:
            fee_int = TransactionType.FEE_REWARD.value
            pool_int = TransactionType.COINBASE_REWARD.value
            rows = await conn.execute_fetchall(
                "SELECT transaction_record from transaction_record WHERE confirmed=1 and (type=? or type=?)",
                (fee_int, pool_int),
            )
        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def get_all_unconfirmed(self) -> List[TransactionRecord]:
        """
        Returns the list of all transaction that have not yet been confirmed.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall("SELECT transaction_record from transaction_record WHERE confirmed=0")
        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def get_unconfirmed_for_wallet(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Returns the list of transaction that have not yet been confirmed.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT transaction_record from transaction_record WHERE confirmed=0 AND wallet_id=?", (wallet_id,)
            )
        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def get_transactions_between(
        self,
        wallet_id: int,
        start,
        end,
        sort_key=None,
        reverse=False,
        confirmed: Optional[bool] = None,
        to_puzzle_hash: Optional[bytes32] = None,
        type_filter: Optional[TransactionTypeFilter] = None,
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

        confirmed_str = ""
        if confirmed is not None:
            confirmed_str = f"AND confirmed={int(confirmed)}"

        if type_filter is None:
            type_filter_str = ""
        else:
            type_filter_str = (
                f"AND type {'' if type_filter.mode == FilterMode.include else 'NOT'} "
                f"IN ({','.join([str(x) for x in type_filter.values])})"
            )

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT transaction_record FROM transaction_record WHERE wallet_id=?{puzz_hash_where}"
                f" {type_filter_str} {confirmed_str} {query_str}, rowid"
                f" LIMIT {start}, {limit}",
                (wallet_id,),
            )

        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def get_transaction_count_for_wallet(
        self,
        wallet_id: int,
        confirmed: Optional[bool] = None,
        type_filter: Optional[TransactionTypeFilter] = None,
    ) -> int:
        confirmed_str = ""
        if confirmed is not None:
            confirmed_str = f"AND confirmed={int(confirmed)}"

        if type_filter is None:
            type_filter_str = ""
        else:
            type_filter_str = (
                f"AND type {'' if type_filter.mode == FilterMode.include else 'NOT'} "
                f"IN ({','.join([str(x) for x in type_filter.values])})"
            )
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(
                await conn.execute_fetchall(
                    f"SELECT COUNT(*) FROM transaction_record where wallet_id=? {type_filter_str} {confirmed_str}",
                    (wallet_id,),
                )
            )
        return 0 if len(rows) == 0 else rows[0][0]

    async def get_all_transactions_for_wallet(self, wallet_id: int, type: int = None) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            if type is None:
                rows = await conn.execute_fetchall(
                    "SELECT transaction_record FROM transaction_record WHERE wallet_id=?", (wallet_id,)
                )
            else:
                rows = await conn.execute_fetchall(
                    "SELECT transaction_record FROM transaction_record WHERE wallet_id=? AND type=?",
                    (
                        wallet_id,
                        type,
                    ),
                )
        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def get_all_transactions(self) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall("SELECT transaction_record from transaction_record")
        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def get_transaction_above(self, height: int) -> List[TransactionRecord]:
        # Can be -1 (get all tx)

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT transaction_record from transaction_record WHERE confirmed_at_height>?", (height,)
            )
        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def get_transactions_by_trade_id(self, trade_id: bytes32) -> List[TransactionRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT transaction_record from transaction_record WHERE trade_id=?", (trade_id,)
            )
        return await self._get_new_tx_records_from_old([TransactionRecordOld.from_bytes(row[0]) for row in rows])

    async def rollback_to_block(self, height: int):
        # Delete from storage
        self.tx_submitted = {}
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM transaction_record WHERE confirmed_at_height>?", (height,))).close()

    async def delete_unconfirmed_transactions(self, wallet_id: int):
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (
                await conn.execute(
                    "DELETE FROM transaction_record WHERE confirmed=0 AND wallet_id=? AND type not in (?,?)",
                    (
                        wallet_id,
                        TransactionType.INCOMING_CLAWBACK_SEND.value,
                        TransactionType.INCOMING_CLAWBACK_RECEIVE.value,
                    ),
                )
            ).close()

    async def _get_new_tx_records_from_old(self, old_records: List[TransactionRecordOld]) -> List[TransactionRecord]:
        tx_id_to_valid_times: Dict[bytes, ConditionValidTimes] = {}
        empty_valid_times = ConditionValidTimes()
        async with self.db_wrapper.reader_no_transaction() as conn:
            chunked_records: List[List[TransactionRecordOld]] = [
                old_records[i : min(len(old_records), i + self.db_wrapper.host_parameter_limit)]
                for i in range(0, len(old_records), self.db_wrapper.host_parameter_limit)
            ]
            for records_chunk in chunked_records:
                cursor = await conn.execute(
                    f"SELECT txid, valid_times from tx_times WHERE txid IN ({','.join('?' * len(records_chunk))})",
                    tuple(tx.name for tx in records_chunk),
                )
                for row in await cursor.fetchall():
                    tx_id_to_valid_times[row[0]] = ConditionValidTimes.from_bytes(row[1])
                await cursor.close()
        return [
            TransactionRecord(
                confirmed_at_height=record.confirmed_at_height,
                created_at_time=record.created_at_time,
                to_puzzle_hash=record.to_puzzle_hash,
                amount=record.amount,
                fee_amount=record.fee_amount,
                confirmed=record.confirmed,
                sent=record.sent,
                spend_bundle=record.spend_bundle,
                additions=record.additions,
                removals=record.removals,
                wallet_id=record.wallet_id,
                sent_to=record.sent_to,
                trade_id=record.trade_id,
                type=record.type,
                name=record.name,
                memos=record.memos,
                valid_times=(
                    tx_id_to_valid_times[record.name] if record.name in tx_id_to_valid_times else empty_valid_times
                ),
            )
            for record in old_records
        ]
