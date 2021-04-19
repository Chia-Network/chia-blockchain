from typing import Any, Dict, List, Optional, Set

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
    cache_size: uint32
    tx_record_cache: Dict[bytes32, TransactionRecord]
    tx_wallet_cache: Dict[int, Dict[Any, Set[bytes32]]]

    @classmethod
    async def create(cls, db_wrapper: DBWrapper, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size
        self.db_wrapper = db_wrapper
        self.db_connection = self.db_wrapper.db

        await self.db_connection.execute("pragma journal_mode=wal")
        await self.db_connection.execute("pragma synchronous=2")
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
        self.tx_record_cache = dict()
        self.tx_wallet_cache = dict()
        return self

    async def _init_cache(self):
        # init cache here
        pass

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
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()
        self.tx_record_cache[record.name] = record

        if record.wallet_id in self.tx_wallet_cache:
            if None in self.tx_wallet_cache[record.wallet_id]:
                self.tx_wallet_cache[record.wallet_id][None].add(record.name)
            if record.type in self.tx_wallet_cache[record.wallet_id]:
                self.tx_wallet_cache[record.wallet_id][record.type].add(record.name)

        if len(self.tx_record_cache) > self.cache_size:
            while len(self.tx_record_cache) > self.cache_size:
                first_in = list(self.tx_record_cache.keys())[0]
                self.tx_record_cache.pop(first_in)

    async def set_confirmed(self, tx_id: bytes32, height: uint32):
        """
        Updates transaction to be confirmed.
        """
        current: Optional[TransactionRecord] = await self.get_transaction_record(tx_id)
        if current is None:
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

    async def unconfirmed_with_removal_coin(self, removal_id: bytes32) -> List[TransactionRecord]:
        """ Returns a record containing removed coin with id: removal_id"""
        result = []
        all_unconfirmed: List[TransactionRecord] = await self.get_all_unconfirmed()
        for record in all_unconfirmed:
            for coin in record.removals:
                if coin.name() == removal_id:
                    result.append(record)

        return result

    async def tx_with_addition_coin(self, removal_id: bytes32, wallet_id: int) -> List[TransactionRecord]:
        """ Returns a record containing removed coin with id: removal_id"""
        result = []
        all_records = await self.get_all_transactions(wallet_id, TransactionType.OUTGOING_TX.value)

        for record in all_records:
            for coin in record.additions:
                if coin.name() == removal_id:
                    result.append(record)

        return result

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

    async def tx_reorged(self, tx_id: bytes32):
        """
        Updates transaction sent count to 0 and resets confirmation data
        """

        current: Optional[TransactionRecord] = await self.get_transaction_record(tx_id)
        if current is None:
            return
        tx: TransactionRecord = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=current.created_at_time,
            to_puzzle_hash=current.to_puzzle_hash,
            amount=current.amount,
            fee_amount=current.fee_amount,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=current.spend_bundle,
            additions=current.additions,
            removals=current.removals,
            wallet_id=current.wallet_id,
            sent_to=[],
            trade_id=None,
            type=current.type,
            name=current.name,
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

        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE sent<? and confirmed=?",
            (
                4,
                0,
            ),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []
        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

    async def get_farming_rewards(self):
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

        cursor = await self.db_connection.execute(
            "SELECT * from transaction_record WHERE confirmed=? and wallet_id=?",
            (
                0,
                wallet_id,
            ),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            record = TransactionRecord.from_bytes(row[0])
            records.append(record)

        return records

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

    async def get_all_transactions(self, wallet_id: int, type: int = None) -> List[TransactionRecord]:
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

        if wallet_id not in self.tx_wallet_cache:
            self.tx_wallet_cache[wallet_id] = {}
        self.tx_wallet_cache[wallet_id][type] = cache_set

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
        self.tx_wallet_cache = {}
        c1 = await self.db_connection.execute("DELETE FROM transaction_record WHERE confirmed_at_height>?", (height,))
        await c1.close()
