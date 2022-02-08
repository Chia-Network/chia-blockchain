import time
from typing import Dict, List, Optional, Tuple

from databases import Database

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.db_wrapper import DBWrapper
from chia.util.errors import Err
from chia.util.ints import uint8, uint32
from chia.util import dialect_utils
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.transaction_type import TransactionType


class WalletTransactionStore:
    """
    WalletTransactionStore stores transaction history for the wallet.
    """
    db_connection: Database
    db_wrapper: DBWrapper
    tx_record_cache: Dict[bytes32, TransactionRecord]
    tx_submitted: Dict[bytes32, Tuple[int, int]]  # tx_id: [time submitted: count]
    unconfirmed_for_wallet: Dict[int, Dict[bytes32, TransactionRecord]]

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        self.db_wrapper = db_wrapper
        self.db_connection = self.db_wrapper.db
        async with self.db_connection.connection() as connection:
            async with connection.transaction():
                await self.db_connection.execute(
                    (
                        "CREATE TABLE IF NOT EXISTS transaction_record("
                        f" transaction_record {dialect_utils.data_type('blob', self.db_connection.url.dialect)},"
                        f" bundle_id {dialect_utils.data_type('text-as-index', self.db_connection.url.dialect)} PRIMARY KEY,"  # NOTE: bundle_id is being stored as bytes, not hex
                        " confirmed_at_height bigint,"
                        " created_at_time bigint,"
                        f" to_puzzle_hash {dialect_utils.data_type('text-as-index', self.db_connection.url.dialect)},"
                        f" amount {dialect_utils.data_type('blob', self.db_connection.url.dialect)},"
                        f" fee_amount {dialect_utils.data_type('blob', self.db_connection.url.dialect)},"
                        " confirmed int,"
                        " sent int,"
                        " wallet_id bigint,"
                        " trade_id text,"
                        " type int)"
                    )
                )

                # Useful for reorg lookups
                await dialect_utils.create_index_if_not_exists(self.db_connection, 'tx_confirmed_index', 'transaction_record', ['confirmed_at_height'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'tx_created_index', 'transaction_record', ['created_at_time'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'tx_confirmed', 'transaction_record', ['confirmed'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'tx_sent', 'transaction_record', ['sent'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'tx_type', 'transaction_record', ['type'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'tx_to_puzzle_hash', 'transaction_record', ['to_puzzle_hash'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'wallet_id', 'transaction_record', ['wallet_id'])

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
        await self.db_connection.execute("DELETE FROM transaction_record")

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
            row_to_insert = {
                "transaction_record": bytes(record),
                "bundle_id": record.name,
                "confirmed_at_height": int(record.confirmed_at_height),
                "created_at_time": int(record.created_at_time),
                "to_puzzle_hash": record.to_puzzle_hash.hex(),
                "amount": bytes(record.amount),
                "fee_amount": bytes(record.fee_amount),
                "confirmed": int(record.confirmed),
                "sent": int(record.sent),
                "wallet_id": int(record.wallet_id),
                "trade_id": record.trade_id,
                "type": int(record.type),
            }
            await self.db_connection.execute(
                dialect_utils.upsert_query('transaction_record', ['bundle_id'], row_to_insert.keys(), self.db_connection.url.dialect),
                row_to_insert
            )
        except BaseException:
            if not in_transaction:
                await self.rebuild_tx_cache()
            raise
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def delete_transaction_record(self, tx_id: bytes32) -> None:
        if tx_id in self.tx_record_cache:
            tx_record = self.tx_record_cache.pop(tx_id)
            if tx_record.wallet_id in self.unconfirmed_for_wallet:
                tx_cache = self.unconfirmed_for_wallet[tx_record.wallet_id]
                if tx_id in tx_cache:
                    tx_cache.pop(tx_id)

        await self.db_connection.execute("DELETE FROM transaction_record WHERE bundle_id=:bundle_id", {"bundle_id": tx_id})

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
            trade_id=record.trade_id,
            type=record.type,
            name=record.name,
            memos=record.memos,
        )
        await self.add_transaction_record(tx, False)

    async def get_transaction_record(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        """
        Checks DB and cache for TransactionRecord with id: id and returns it.
        """
        if tx_id in self.tx_record_cache:
            return self.tx_record_cache[tx_id]

        # NOTE: bundle_id is being stored as bytes, not hex
        row = await self.db_connection.fetch_one("SELECT * from transaction_record WHERE bundle_id=:bundle_id", {"bundle_id": tx_id})
        if row is not None:
            record = TransactionRecord.from_bytes(row[0])
            return record
        return None

    async def get_not_sent(self) -> List[TransactionRecord]:
        """
        Returns the list of transaction that have not been received by full node yet.
        """
        current_time = int(time.time())
        rows = await self.db_connection.fetch_all(
            "SELECT * from transaction_record WHERE confirmed=:confirmed",
            {"confirmed": 0},
        )
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
        rows = await self.db_connection.fetch_all(
            "SELECT * from transaction_record WHERE confirmed=:confirmed and (type=:fee_int or type=:pool_int)", {"confirmed": 1, "fee_int":  int(fee_int), "pool_int":  int(pool_int)}
        )
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_all_unconfirmed(self) -> List[TransactionRecord]:
        """
        Returns the list of all transaction that have not yet been confirmed.
        """

        rows = await self.db_connection.fetch_all("SELECT * from transaction_record WHERE confirmed=:confirmed", {"confirmed": 0})
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

    async def get_transactions_between(
        self, wallet_id: int, start, end, sort_key=None, reverse=False
    ) -> List[TransactionRecord]:
        """Return a list of transaction between start and end index. List is in reverse chronological order.
        start = 0 is most recent transaction
        """
        limit = end - start

        if sort_key is None:
            sort_key = "CONFIRMED_AT_HEIGHT"
        if sort_key not in SortKey.__members__:
            raise ValueError(f"There is no known sort {sort_key}")

        if reverse:
            query_str = SortKey[sort_key].descending()
        else:
            query_str = SortKey[sort_key].ascending()

        rows = await self.db_connection.fetch_all(
            f"SELECT * from transaction_record where wallet_id=:wallet_id" f" {query_str}, rowid" f" LIMIT {int(start)}, {int(limit)}",
            {"wallet_id": int(wallet_id)},
        )
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_transaction_count_for_wallet(self, wallet_id) -> int:
        count_result = await self.db_connection.fetch_one(
            "SELECT COUNT(*) FROM transaction_record where wallet_id=:wallet_id", {"wallet_id": int(wallet_id)}
        )
        if count_result is not None:
            count = count_result[0]
        else:
            count = 0
        return count

    async def get_all_transactions_for_wallet(self, wallet_id: int, type: int = None) -> List[TransactionRecord]:
        """
        Returns all stored transactions.
        """
        if type is None:
            rows = await self.db_connection.fetch_all(
                "SELECT * from transaction_record where wallet_id=:wallet_id", {"wallet_id": int(wallet_id)}
            )
        else:
            rows = await self.db_connection.fetch_all(
                "SELECT * from transaction_record where wallet_id=:wallet_id and type=:type",
                {
                    "wallet_id": int(wallet_id),
                    "type": int(type),
                }
            )

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
        rows = await self.db_connection.fetch_all("SELECT * from transaction_record")
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_transaction_above(self, height: int) -> List[TransactionRecord]:
        # Can be -1 (get all tx)

        rows = await self.db_connection.fetch_all(
            "SELECT * from transaction_record WHERE confirmed_at_height>:min_confirmed_at_height", {"min_confirmed_at_height": int(height)}
        )
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_transactions_by_trade_id(self, trade_id: bytes32) -> List[TransactionRecord]:
        rows = await self.db_connection.fetch_all("SELECT * from transaction_record WHERE trade_id=:trade_id", {"trade_id": trade_id})
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
        self.tx_submitted = {}
        await self.db_connection.execute("DELETE FROM transaction_record WHERE confirmed_at_height>:min_confirmed_at_height", {"min_confirmed_at_height": int(height)})

    async def delete_unconfirmed_transactions(self, wallet_id: int):
        await self.db_connection.execute(
            "DELETE FROM transaction_record WHERE confirmed=0 AND wallet_id=:wallet_id", {"wallet_id": int(wallet_id)}
        )
