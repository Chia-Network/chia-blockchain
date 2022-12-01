from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Set

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32, uint64
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord


class WalletCoinStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, wrapper: DBWrapper2):
        self = cls()

        self.db_wrapper = wrapper

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

        return self

    async def count_small_unspent(self, cutoff: int) -> int:
        amount_bytes = bytes(uint64(cutoff))
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn, "SELECT COUNT(*) FROM coin_record WHERE amount < ? AND spent=0", (amount_bytes,)
            )
            return int(0 if row is None else row[0])

    async def get_multiple_coin_records(self, coin_names: List[bytes32]) -> List[WalletCoinRecord]:
        """Return WalletCoinRecord(s) that have a coin name in the specified list"""
        if len(coin_names) == 0:
            return []

        as_hexes = [cn.hex() for cn in coin_names]
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                f'SELECT * from coin_record WHERE coin_name in ({"?," * (len(as_hexes) - 1)}?)', tuple(as_hexes)
            )

        return [self.coin_record_from_row(row) for row in rows]

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: WalletCoinRecord, name: Optional[bytes32] = None) -> None:
        if name is None:
            name = record.name()
        assert record.spent == (record.spent_block_height != 0)
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
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

    # Sometimes we realize that a coin is actually not interesting to us so we need to delete it
    async def delete_coin_record(self, coin_name: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM coin_record WHERE coin_name=?", (coin_name.hex(),))).close()

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

    def coin_record_from_row(self, row: sqlite3.Row) -> WalletCoinRecord:
        coin = Coin(bytes32.fromhex(row[6]), bytes32.fromhex(row[5]), uint64.from_bytes(row[7]))
        return WalletCoinRecord(
            coin, uint32(row[1]), uint32(row[2]), bool(row[3]), bool(row[4]), WalletType(row[8]), row[9]
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
        coin_names: List[bytes32],
        include_spent_coins: bool = True,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> List[Optional[WalletCoinRecord]]:
        """Returns CoinRecord with specified coin id."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(
                await conn.execute_fetchall(
                    f"SELECT * from coin_record WHERE coin_name in ({','.join('?'*len(coin_names))}) "
                    f"AND confirmed_height>=? AND confirmed_height<? "
                    f"{'' if include_spent_coins else 'AND spent=0'}",
                    tuple([c.hex() for c in coin_names]) + (start_height, end_height),
                )
            )

        ret: Dict[bytes32, WalletCoinRecord] = {}
        for row in rows:
            record = self.coin_record_from_row(row)
            coin_name = bytes32.fromhex(row[0])
            ret[coin_name] = record

        return [ret.get(name) for name in coin_names]

    async def get_first_coin_height(self) -> Optional[uint32]:
        """Returns height of first confirmed coin"""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(await conn.execute_fetchall("SELECT MIN(confirmed_height) FROM coin_record"))

        if len(rows) != 0 and rows[0][0] is not None:
            return uint32(rows[0][0])

        return None

    async def get_unspent_coins_for_wallet(self, wallet_id: int) -> Set[WalletCoinRecord]:
        """Returns set of CoinRecords that have not been spent yet for a wallet."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM coin_record WHERE wallet_id=? AND spent_height=0", (wallet_id,)
            )
        return set(self.coin_record_from_row(row) for row in rows)

    async def get_all_unspent_coins(self) -> Set[WalletCoinRecord]:
        """Returns set of CoinRecords that have not been spent yet for a wallet."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall("SELECT * FROM coin_record WHERE spent_height=0")
        return set(self.coin_record_from_row(row) for row in rows)

    async def get_coin_names_to_check(self, check_height) -> Set[bytes32]:
        """Returns set of all CoinRecords."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT coin_name from coin_record where spent_height=0 or spent_height>? or confirmed_height>?",
                (
                    check_height,
                    check_height,
                ),
            )

        return set(bytes32.fromhex(row[0]) for row in rows)

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
