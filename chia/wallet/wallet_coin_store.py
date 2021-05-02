import asyncio
from typing import Dict, List, Optional, Set

import aiosqlite
import sqlite3

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord


class WalletCoinStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    db_connection: aiosqlite.Connection
    coin_record_cache: Dict[bytes32, WalletCoinRecord]
    coin_wallet_record_cache: Dict[int, Dict[bytes32, WalletCoinRecord]]
    wallet_cache_lock: asyncio.Lock
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, wrapper: DBWrapper):
        self = cls()

        self.db_connection = wrapper.db
        self.db_wrapper = wrapper
        await self.db_connection.execute("pragma journal_mode=wal")
        await self.db_connection.execute("pragma synchronous=2")

        await self.db_connection.execute(
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
        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed_height on coin_record(confirmed_height)"
        )
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS coin_spent_height on coin_record(spent_height)")
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS coin_spent on coin_record(spent)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS coin_puzzlehash on coin_record(puzzle_hash)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS wallet_type on coin_record(wallet_type)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS wallet_id on coin_record(wallet_id)")

        await self.db_connection.commit()
        self.coin_record_cache = dict()
        self.coin_wallet_record_cache = {}
        all_coins = await self.get_all_coins()
        for coin_record in all_coins:
            self.coin_record_cache[coin_record.coin.name()] = coin_record

        self.wallet_cache_lock = asyncio.Lock()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM coin_record")
        await cursor.close()
        await self.db_connection.commit()

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: WalletCoinRecord) -> None:
        # update wallet cache

        await self.wallet_cache_lock.acquire()
        try:
            if record.wallet_id in self.coin_wallet_record_cache:
                cache_dict = self.coin_wallet_record_cache[record.wallet_id]
                if record.coin.name() in cache_dict and record.spent:
                    cache_dict.pop(record.coin.name())
                else:
                    cache_dict[record.coin.name()] = record

            cursor = await self.db_connection.execute(
                "INSERT OR REPLACE INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.coin.name().hex(),
                    record.confirmed_block_height,
                    record.spent_block_height,
                    int(record.spent),
                    int(record.coinbase),
                    str(record.coin.puzzle_hash.hex()),
                    str(record.coin.parent_coin_info.hex()),
                    bytes(record.coin.amount),
                    record.wallet_type,
                    record.wallet_id,
                ),
            )
            await cursor.close()
            self.coin_record_cache[record.coin.name()] = record
        finally:
            self.wallet_cache_lock.release()

    # Update coin_record to be spent in DB
    async def set_spent(self, coin_name: bytes32, height: uint32):
        current: Optional[WalletCoinRecord] = await self.get_coin_record(coin_name)
        if current is None:
            return

        spent: WalletCoinRecord = WalletCoinRecord(
            current.coin,
            current.confirmed_block_height,
            height,
            True,
            current.coinbase,
            current.wallet_type,
            current.wallet_id,
        )

        await self.add_coin_record(spent)

    def coin_record_from_row(self, row: sqlite3.Row) -> WalletCoinRecord:
        coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
        return WalletCoinRecord(
            coin, uint32(row[1]), uint32(row[2]), bool(row[3]), bool(row[4]), WalletType(row[8]), row[9]
        )

    async def get_coin_record(self, coin_name: bytes32) -> Optional[WalletCoinRecord]:
        """ Returns CoinRecord with specified coin id. """
        if coin_name in self.coin_record_cache:
            return self.coin_record_cache[coin_name]
        cursor = await self.db_connection.execute("SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),))
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None
        return self.coin_record_from_row(row)

    async def get_first_coin_height(self) -> Optional[uint32]:
        """ Returns height of first confirmed coin"""
        cursor = await self.db_connection.execute("SELECT MIN(confirmed_height) FROM coin_record;")
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] is not None:
            return uint32(row[0])

        return None

    async def get_unspent_coins_at_height(self, height: Optional[uint32] = None) -> Set[WalletCoinRecord]:
        """
        Returns set of CoinRecords that have not been spent yet. If a height is specified,
        We can also return coins that were unspent at this height (but maybe spent later).
        Finally, the coins must be confirmed at the height or less.
        """
        if height is None:
            all_unspent = set()
            for name, coin_record in self.coin_record_cache.items():
                if coin_record.spent is False:
                    all_unspent.add(coin_record)
            return all_unspent
        else:
            all_unspent = set()
            for name, coin_record in self.coin_record_cache.items():
                if (
                    coin_record.spent is False
                    or coin_record.spent_block_height > height >= coin_record.confirmed_block_height
                ):
                    all_unspent.add(coin_record)
            return all_unspent

    async def get_unspent_coins_for_wallet(self, wallet_id: int) -> Set[WalletCoinRecord]:
        """ Returns set of CoinRecords that have not been spent yet for a wallet. """
        async with self.wallet_cache_lock:
            if wallet_id in self.coin_wallet_record_cache:
                wallet_coins: Dict[bytes32, WalletCoinRecord] = self.coin_wallet_record_cache[wallet_id]
                return set(wallet_coins.values())

            coin_set = set()

            cursor = await self.db_connection.execute(
                "SELECT * from coin_record WHERE spent=0 and wallet_id=?",
                (wallet_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            cache_dict = {}
            for row in rows:
                coin_record = self.coin_record_from_row(row)
                coin_set.add(coin_record)
                cache_dict[coin_record.name()] = coin_record

            self.coin_wallet_record_cache[wallet_id] = cache_dict
            return coin_set

    async def get_all_coins(self) -> Set[WalletCoinRecord]:
        """ Returns set of all CoinRecords."""
        cursor = await self.db_connection.execute("SELECT * from coin_record")
        rows = await cursor.fetchall()
        await cursor.close()

        return set(self.coin_record_from_row(row) for row in rows)

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(self, puzzle_hash: bytes32) -> List[WalletCoinRecord]:
        """Returns a list of all coin records with the given puzzle hash"""
        cursor = await self.db_connection.execute("SELECT * from coin_record WHERE puzzle_hash=?", (puzzle_hash.hex(),))
        rows = await cursor.fetchall()
        await cursor.close()

        return [self.coin_record_from_row(row) for row in rows]

    async def get_coin_record_by_coin_id(self, coin_id: bytes32) -> Optional[WalletCoinRecord]:
        """Returns a coin records with the given name, if it exists"""
        # TODO: This is a duplicate of get_coin_record()
        return await self.get_coin_record(coin_id)

    async def rollback_to_block(self, height: int):
        """
        Rolls back the blockchain to block_index. All blocks confirmed after this point
        are removed from the LCA. All coins confirmed after this point are removed.
        All coins spent after this point are set to unspent. Can be -1 (rollback all)
        """
        # Update memory cache

        delete_queue: List[WalletCoinRecord] = []
        for coin_name, coin_record in self.coin_record_cache.items():
            if coin_record.spent_block_height > height:
                new_record = WalletCoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_height,
                    coin_record.spent_block_height,
                    False,
                    coin_record.coinbase,
                    coin_record.wallet_type,
                    coin_record.wallet_id,
                )
                self.coin_record_cache[coin_record.coin.name()] = new_record
            if coin_record.confirmed_block_height > height:
                delete_queue.append(coin_record)

        for coin_record in delete_queue:
            self.coin_record_cache.pop(coin_record.coin.name())
            if coin_record.wallet_id in self.coin_wallet_record_cache:
                coin_cache = self.coin_wallet_record_cache[coin_record.wallet_id]
                if coin_record.coin.name() in coin_cache:
                    coin_cache.pop(coin_record.coin.name())

        # Delete from storage
        c1 = await self.db_connection.execute("DELETE FROM coin_record WHERE confirmed_height>?", (height,))
        await c1.close()
        c2 = await self.db_connection.execute(
            "UPDATE coin_record SET spent_height = 0, spent = 0 WHERE spent_height>?",
            (height,),
        )
        await c2.close()
