from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, Optional, Set

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64
from chia.util.lru_cache import LRUCache
from chia.util.misc import UInt32Range, UInt64Range, VersionedBlob
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.query_filter import AmountFilter, FilterMode, HashFilter
from chia.wallet.util.wallet_types import CoinType, WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord

unspent_range = UInt32Range(stop=uint32(0))


class CoinRecordOrder(IntEnum):
    confirmed_height = 1
    spent_height = 2


@streamable
@dataclass(frozen=True)
class GetCoinRecords(Streamable):
    offset: uint32 = uint32(0)
    limit: uint32 = uint32.MAXIMUM
    wallet_id: Optional[uint32] = None
    wallet_type: Optional[uint8] = None  # WalletType
    coin_type: Optional[uint8] = None  # CoinType
    coin_id_filter: Optional[HashFilter] = None
    puzzle_hash_filter: Optional[HashFilter] = None
    parent_coin_id_filter: Optional[HashFilter] = None
    amount_filter: Optional[AmountFilter] = None
    amount_range: Optional[UInt64Range] = None
    confirmed_range: Optional[UInt32Range] = None
    spent_range: Optional[UInt32Range] = None
    order: uint8 = uint8(CoinRecordOrder.confirmed_height)
    reverse: bool = False
    include_total_count: bool = False  # Include the total number of entries for the query without applying offset/limit


@dataclass(frozen=True)
class GetCoinRecordsResult:
    records: List[WalletCoinRecord]
    coin_id_to_record: Dict[bytes32, WalletCoinRecord]
    total_count: Optional[uint32]


class WalletCoinStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    db_wrapper: DBWrapper2
    total_count_cache: LRUCache[bytes32, uint32]

    @classmethod
    async def create(cls, wrapper: DBWrapper2):
        self = cls()

        self.db_wrapper = wrapper
        self.total_count_cache = LRUCache(100)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS coin_record("
                    "coin_name text PRIMARY KEY,"
                    " confirmed_height bigint,"
                    " spent_height bigint,"
                    " spent int,"
                    " coinbase int,"
                    " puzzle_hash text,"
                    " coin_parent text,"
                    " amount blob,"
                    " wallet_type int,"
                    " wallet_id int)"
                )
            )

            # Useful for reorg lookups
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_confirmed_height on coin_record(confirmed_height)")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_spent_height on coin_record(spent_height)")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_spent on coin_record(spent)")

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_puzzlehash on coin_record(puzzle_hash)")

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_record_wallet_type on coin_record(wallet_type)")

            await conn.execute("CREATE INDEX IF NOT EXISTS wallet_id on coin_record(wallet_id)")

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_amount on coin_record(amount)")

            try:
                await conn.execute("ALTER TABLE coin_record ADD COLUMN coin_type int DEFAULT 0")
                await conn.execute("ALTER TABLE coin_record ADD COLUMN metadata blob")
                await conn.execute("CREATE INDEX IF NOT EXISTS coin_record_coin_type on coin_record(coin_type)")
            except sqlite3.OperationalError:
                pass
        return self

    async def count_small_unspent(self, cutoff: int, coin_type: CoinType = CoinType.NORMAL) -> int:
        amount_bytes = bytes(uint64(cutoff))
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT COUNT(*) FROM coin_record WHERE coin_type=? AND amount < ? AND spent=0",
                (coin_type, amount_bytes),
            )
            return int(0 if row is None else row[0])

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: WalletCoinRecord, name: Optional[bytes32] = None) -> None:
        if name is None:
            name = record.name()
        assert record.spent == (record.spent_block_height != 0)
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "INSERT OR REPLACE INTO coin_record ("
                "coin_name, confirmed_height, spent_height, spent, coinbase, puzzle_hash, coin_parent, amount, "
                "wallet_type, wallet_id, coin_type, metadata) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name.hex(),
                    record.confirmed_block_height,
                    record.spent_block_height,
                    int(record.spent),
                    int(record.coinbase),
                    str(record.coin.puzzle_hash.hex()),
                    str(record.coin.parent_coin_info.hex()),
                    bytes(uint64(record.coin.amount)),
                    record.wallet_type,
                    record.wallet_id,
                    record.coin_type,
                    None if record.metadata is None else bytes(record.metadata),
                ),
            )
        self.total_count_cache.cache.clear()

    # Sometimes we realize that a coin is actually not interesting to us so we need to delete it
    async def delete_coin_record(self, coin_name: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM coin_record WHERE coin_name=?", (coin_name.hex(),))).close()
        self.total_count_cache.cache.clear()

    # Update coin_record to be spent in DB
    async def set_spent(self, coin_name: bytes32, height: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "UPDATE coin_record SET spent_height=?,spent=? WHERE coin_name=?",
                (
                    height,
                    1,
                    coin_name.hex(),
                ),
            )
        self.total_count_cache.cache.clear()

    def coin_record_from_row(self, row: sqlite3.Row) -> WalletCoinRecord:
        coin = Coin(bytes32.fromhex(row[6]), bytes32.fromhex(row[5]), uint64.from_bytes(row[7]))
        return WalletCoinRecord(
            coin,
            uint32(row[1]),
            uint32(row[2]),
            bool(row[3]),
            bool(row[4]),
            WalletType(row[8]),
            row[9],
            CoinType(row[10]),
            None if row[11] is None else VersionedBlob.from_bytes(row[11]),
        )

    async def get_coin_record(self, coin_name: bytes32) -> Optional[WalletCoinRecord]:
        """Returns CoinRecord with specified coin id."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(await conn.execute_fetchall("SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),)))

        if len(rows) == 0:
            return None
        return self.coin_record_from_row(rows[0])

    async def get_coin_records(
        self,
        *,
        offset: uint32 = uint32(0),
        limit: uint32 = uint32.MAXIMUM,
        wallet_id: Optional[uint32] = None,
        wallet_type: Optional[WalletType] = None,
        coin_type: Optional[CoinType] = None,
        coin_id_filter: Optional[HashFilter] = None,
        puzzle_hash_filter: Optional[HashFilter] = None,
        parent_coin_id_filter: Optional[HashFilter] = None,
        amount_filter: Optional[AmountFilter] = None,
        amount_range: Optional[UInt64Range] = None,
        confirmed_range: Optional[UInt32Range] = None,
        spent_range: Optional[UInt32Range] = None,
        order: CoinRecordOrder = CoinRecordOrder.confirmed_height,
        reverse: bool = False,
        include_total_count: bool = False,
    ) -> GetCoinRecordsResult:
        conditions = []
        if wallet_id is not None:
            conditions.append(f"wallet_id={wallet_id}")
        if wallet_type is not None:
            conditions.append(f"wallet_type={wallet_type.value}")
        if coin_type is not None:
            conditions.append(f"coin_type={coin_type.value}")
        for field, hash_filter in {
            "coin_name": coin_id_filter,
            "coin_parent": parent_coin_id_filter,
            "puzzle_hash": puzzle_hash_filter,
        }.items():
            if hash_filter is None:
                continue
            entries = ",".join(f"{value.hex()!r}" for value in hash_filter.values)
            conditions.append(
                f"{field} {'not' if FilterMode(hash_filter.mode) == FilterMode.exclude else ''} in ({entries})"
            )
        if confirmed_range is not None and confirmed_range != UInt32Range():
            conditions.append(f"confirmed_height BETWEEN {confirmed_range.start} AND {confirmed_range.stop}")
        if spent_range is not None and spent_range != UInt32Range():
            conditions.append(f"spent_height BETWEEN {spent_range.start} AND {spent_range.stop}")
        if amount_filter is not None:
            entries = ",".join(f"X'{bytes(value).hex()}'" for value in amount_filter.values)
            conditions.append(
                f"amount {'not' if FilterMode(amount_filter.mode) == FilterMode.exclude else ''} in ({entries})"
            )
        if amount_range is not None and amount_range != UInt64Range():
            conditions.append(
                f"amount BETWEEN X'{bytes(amount_range.start).hex()}' AND X'{bytes(amount_range.stop).hex()}'"
            )

        where_sql = "WHERE " + " AND ".join(conditions) if len(conditions) > 0 else ""
        order_sql = f"ORDER BY {order.name} {'DESC' if reverse else 'ASC'}, rowid"
        limit_sql = f"LIMIT {offset}, {limit}" if offset > 0 or limit < uint32.MAXIMUM else ""
        query_sql = f"{where_sql} {order_sql} {limit_sql}"

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(f"SELECT * FROM coin_record {query_sql}")

            total_count = None
            if include_total_count:
                cache_hash = std_hash(bytes(where_sql, encoding="utf8"))  # Only use the conditions here
                total_count = self.total_count_cache.get(cache_hash)
                if total_count is None:
                    row = await execute_fetchone(conn, f"SELECT COUNT(coin_name) FROM coin_record {where_sql}")
                    assert row is not None and len(row) == 1, "COUNT should always return one value"
                    total_count = uint32(row[0])
                    self.total_count_cache.put(cache_hash, total_count)

        records: List[WalletCoinRecord] = []
        coin_id_to_record: Dict[bytes32, WalletCoinRecord] = {}
        for row in rows:
            records.append(self.coin_record_from_row(row))
            coin_id_to_record[bytes32.fromhex(row[0])] = records[-1]

        return GetCoinRecordsResult(
            records,
            coin_id_to_record,
            total_count,
        )

    async def get_coin_records_between(
        self, wallet_id: int, start: int, end: int, reverse: bool = False, coin_type: CoinType = CoinType.NORMAL
    ) -> List[WalletCoinRecord]:
        """Return a list of coins between start and end index. List is in reverse chronological order.
        start = 0 is most recent transaction
        """
        limit = end - start
        query_str = "ORDER BY confirmed_height " + ("DESC" if reverse else "ASC")

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT * FROM coin_record WHERE coin_type=? AND"
                f" wallet_id=? {query_str}, rowid LIMIT {start}, {limit}",
                (coin_type, wallet_id),
            )
        return [self.coin_record_from_row(row) for row in rows]

    async def get_first_coin_height(self) -> Optional[uint32]:
        """Returns height of first confirmed coin"""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(await conn.execute_fetchall("SELECT MIN(confirmed_height) FROM coin_record"))

        if len(rows) != 0 and rows[0][0] is not None:
            return uint32(rows[0][0])

        return None

    async def get_unspent_coins_for_wallet(
        self, wallet_id: int, coin_type: CoinType = CoinType.NORMAL
    ) -> Set[WalletCoinRecord]:
        """Returns set of CoinRecords that have not been spent yet for a wallet."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM coin_record WHERE coin_type=? AND wallet_id=? AND spent_height=0",
                (coin_type, wallet_id),
            )
        return set(self.coin_record_from_row(row) for row in rows)

    async def get_all_unspent_coins(self, coin_type: CoinType = CoinType.NORMAL) -> Set[WalletCoinRecord]:
        """Returns set of CoinRecords that have not been spent yet for a wallet."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM coin_record WHERE coin_type=? AND spent_height=0", (coin_type,)
            )
        return set(self.coin_record_from_row(row) for row in rows)

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(self, puzzle_hash: bytes32) -> List[WalletCoinRecord]:
        """Returns a list of all coin records with the given puzzle hash"""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall("SELECT * from coin_record WHERE puzzle_hash=?", (puzzle_hash.hex(),))

        return [self.coin_record_from_row(row) for row in rows]

    # Checks DB and DiffStores for CoinRecords with parent_coin_info and returns them
    async def get_coin_records_by_parent_id(self, parent_coin_info: bytes32) -> List[WalletCoinRecord]:
        """Returns a list of all coin records with the given parent id"""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * from coin_record WHERE coin_parent=?", (parent_coin_info.hex(),)
            )

        return [self.coin_record_from_row(row) for row in rows]

    async def rollback_to_block(self, height: int) -> None:
        """
        Rolls back the blockchain to block_index. All coins confirmed after this point are removed.
        All coins spent after this point are set to unspent. Can be -1 (rollback all)
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM coin_record WHERE confirmed_height>?", (height,))).close()
            await (
                await conn.execute(
                    "UPDATE coin_record SET spent_height = 0, spent = 0 WHERE spent_height>?",
                    (height,),
                )
            ).close()
        self.total_count_cache.cache.clear()

    async def delete_wallet(self, wallet_id: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute("DELETE FROM coin_record WHERE wallet_id=?", (wallet_id,))
            await cursor.close()
        self.total_count_cache.cache.clear()
