from typing import List, Optional, Set

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
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, wrapper: DBWrapper):
        self = cls()

        self.db_connection = wrapper.db
        self.db_wrapper = wrapper
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

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_record_wallet_type on coin_record(wallet_type)"
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS wallet_id on coin_record(wallet_id)")

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM coin_record")
        await cursor.close()
        await self.db_connection.commit()

    async def get_multiple_coin_records(self, coin_names: List[bytes32]) -> List[WalletCoinRecord]:
        """Return WalletCoinRecord(s) that have a coin name in the specified list"""
        if len(coin_names) == 0:
            return []

        as_hexes = [cn.hex() for cn in coin_names]
        rows = await self.db_connection.execute_fetchall(
            f'SELECT * from coin_record WHERE coin_name in ({"?," * (len(as_hexes) - 1)}?)', tuple(as_hexes)
        )

        return [self.coin_record_from_row(row) for row in rows]

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: WalletCoinRecord, name: Optional[bytes32] = None) -> None:
        if name is None:
            name = record.name()
        assert record.spent == (record.spent_block_height != 0)
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            ),
        )
        await cursor.close()

    # Sometimes we realize that a coin is actually not interesting to us so we need to delete it
    async def delete_coin_record(self, coin_name: bytes32) -> None:
        c = await self.db_connection.execute("DELETE FROM coin_record WHERE coin_name=?", (coin_name.hex(),))
        await c.close()

    # Update coin_record to be spent in DB
    async def set_spent(self, coin_name: bytes32, height: uint32) -> WalletCoinRecord:
        current: Optional[WalletCoinRecord] = await self.get_coin_record(coin_name)
        assert current is not None
        # assert current.spent is False

        spent: WalletCoinRecord = WalletCoinRecord(
            current.coin,
            current.confirmed_block_height,
            height,
            True,
            current.coinbase,
            current.wallet_type,
            current.wallet_id,
        )

        await self.add_coin_record(spent, coin_name)
        return spent

    def coin_record_from_row(self, row: sqlite3.Row) -> WalletCoinRecord:
        coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
        return WalletCoinRecord(
            coin, uint32(row[1]), uint32(row[2]), bool(row[3]), bool(row[4]), WalletType(row[8]), row[9]
        )

    async def get_coin_record(self, coin_name: bytes32) -> Optional[WalletCoinRecord]:
        """Returns CoinRecord with specified coin id."""
        rows = list(
            await self.db_connection.execute_fetchall("SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),))
        )

        if len(rows) == 0:
            return None
        return self.coin_record_from_row(rows[0])

    async def get_first_coin_height(self) -> Optional[uint32]:
        """Returns height of first confirmed coin"""
        rows = list(await self.db_connection.execute_fetchall("SELECT MIN(confirmed_height) FROM coin_record"))

        if len(rows) != 0 and rows[0][0] is not None:
            return uint32(rows[0][0])

        return None

    async def get_unspent_coins_for_wallet(self, wallet_id: int) -> Set[WalletCoinRecord]:
        """Returns set of CoinRecords that have not been spent yet for a wallet."""
        rows = await self.db_connection.execute_fetchall(
            "SELECT * FROM coin_record WHERE wallet_id=? AND spent_height=0", (wallet_id,)
        )
        return set(self.coin_record_from_row(row) for row in rows)

    async def get_coins_to_check(self, check_height) -> Set[WalletCoinRecord]:
        """Returns set of all CoinRecords."""
        rows = await self.db_connection.execute_fetchall(
            "SELECT * from coin_record where spent_height=0 or spent_height>? or confirmed_height>?",
            (
                check_height,
                check_height,
            ),
        )

        return set(self.coin_record_from_row(row) for row in rows)

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(self, puzzle_hash: bytes32) -> List[WalletCoinRecord]:
        """Returns a list of all coin records with the given puzzle hash"""
        rows = await self.db_connection.execute_fetchall(
            "SELECT * from coin_record WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )

        return [self.coin_record_from_row(row) for row in rows]

    # Checks DB and DiffStores for CoinRecords with parent_coin_info and returns them
    async def get_coin_records_by_parent_id(self, parent_coin_info: bytes32) -> List[WalletCoinRecord]:
        """Returns a list of all coin records with the given parent id"""
        rows = await self.db_connection.execute_fetchall(
            "SELECT * from coin_record WHERE coin_parent=?", (parent_coin_info.hex(),)
        )

        return [self.coin_record_from_row(row) for row in rows]

    async def rollback_to_block(self, height: int):
        """
        Rolls back the blockchain to block_index. All coins confirmed after this point are removed.
        All coins spent after this point are set to unspent. Can be -1 (rollback all)
        """

        c1 = await self.db_connection.execute("DELETE FROM coin_record WHERE confirmed_height>?", (height,))
        await c1.close()
        c2 = await self.db_connection.execute(
            "UPDATE coin_record SET spent_height = 0, spent = 0 WHERE spent_height>?",
            (height,),
        )
        await c2.close()
