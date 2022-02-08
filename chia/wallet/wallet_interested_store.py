from typing import List, Tuple, Optional

from databases import Database

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.util import dialect_utils


class WalletInterestedStore:
    """
    Stores coin ids that we are interested in receiving
    """
    db_connection: Database
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, wrapper: DBWrapper):
        self = cls()

        self.db_connection = wrapper.db
        self.db_wrapper = wrapper
        async with self.db_connection.connection() as connection:
            async with connection.transaction():
                await self.db_connection.execute(f"CREATE TABLE IF NOT EXISTS interested_coins(coin_name {dialect_utils.data_type('text-as-index', self.db_connection.url.dialect)} PRIMARY KEY)")

                await self.db_connection.execute(
                    f"CREATE TABLE IF NOT EXISTS interested_puzzle_hashes(puzzle_hash {dialect_utils.data_type('text-as-index', self.db_connection.url.dialect)} PRIMARY KEY, wallet_id integer)"
                )
        return self

    async def _clear_database(self):
        async with self.db_connection.connection() as connection:
            async with connection.transaction():
                await self.db_connection.execute("DELETE FROM puzzle_hashes")
                await self.db_connection.execute("DELETE FROM interested_coins")

    async def get_interested_coin_ids(self) -> List[bytes32]:
        rows_hex = await self.db_connection.fetch_all("SELECT coin_name FROM interested_coins")
        return [bytes32(bytes.fromhex(row[0])) for row in rows_hex]

    async def add_interested_coin_id(self, coin_id: bytes32, in_transaction: bool = False) -> None:

        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            row_to_insert = {"coin_name": coin_id.hex()}
            await self.db_connection.execute(
                dialect_utils.upsert_query('interested_coins', ['coin_name'], row_to_insert.keys(), self.db_connection.url.dialect),
                row_to_insert
            )
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def get_interested_puzzle_hashes(self) -> List[Tuple[bytes32, int]]:
        rows_hex = await self.db_connection.fetch_all("SELECT puzzle_hash, wallet_id FROM interested_puzzle_hashes")
        return [(bytes32(bytes.fromhex(row[0])), row[1]) for row in rows_hex]

    async def get_interested_puzzle_hash_wallet_id(self, puzzle_hash: bytes32) -> Optional[int]:
        row = await self.db_connection.fetch_one(
            "SELECT wallet_id FROM interested_puzzle_hashes WHERE puzzle_hash=:puzzle_hash", {"puzzle_hash": puzzle_hash.hex()}
        )
        if row is None:
            return None
        return row[0]

    async def add_interested_puzzle_hash(
        self, puzzle_hash: bytes32, wallet_id: int, in_transaction: bool = False
    ) -> None:

        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            row_to_insert = {"puzzle_hash": puzzle_hash.hex(), "wallet_id":  int(wallet_id)}
            await self.db_connection.execute(
                dialect_utils.upsert_query('interested_puzzle_hashes', ['puzzle_hash'], row_to_insert.keys(), self.db_connection.url.dialect),
                row_to_insert
            )
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def remove_interested_puzzle_hash(self, puzzle_hash: bytes32, in_transaction: bool = False) -> None:
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            await self.db_connection.execute(
                "DELETE FROM interested_puzzle_hashes WHERE puzzle_hash=:puzzle_hash", {"puzzle_hash": puzzle_hash.hex()}
            )
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()
