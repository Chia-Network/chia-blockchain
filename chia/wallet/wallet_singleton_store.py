from __future__ import annotations
import json
import logging
from sqlite3 import Row
from typing import List, Tuple, Optional, Any, TypeVar
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.wallet import singleton
from chia.types.coin_spend import CoinSpend
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton import (
    get_most_recent_singleton_coin_from_coin_spend,
    get_innerpuzzle_from_puzzle,
    get_singleton_id_from_puzzle,
)
from chia.wallet.singleton_record import SingletonRecord
from chia.util.condition_tools import ConditionOpcode, conditions_dict_for_solution
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32

from clvm.casts import int_from_bytes

log = logging.getLogger(__name__)
_T_WalletSingletonStore = TypeVar("_T_WalletSingletonStore", bound="WalletSingletonStore")
CONFIRMED_COLS = ("coin_id, coin, singleton_id, wallet_id, parent_coin_spend, "
                 "inner_puzzle_hash, removed_height, lineage_proof, custom_data")
UNCONFIRMED_COLS = "coin_id, singleton_id, wallet_id, coin_spend"

class WalletSingletonStore:
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls: Type[_T_WalletSingletonStore], wrapper: DBWrapper2) -> _T_WalletSingletonStore:
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS confirmed_singletons("
                    "coin_id blob PRIMARY KEY,"
                    " coin text,"
                    " singleton_id blob,"
                    " wallet_id int,"
                    " parent_coin_spend blob,"
                    " inner_puzzle_hash blob,"
                    " removed_height int,"
                    " lineage_proof blob,"
                    " custom_data blob)"
                )
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_index on confirmed_singletons(coin)")
            await conn.execute("CREATE INDEX IF NOT EXISTS singleton_id_index on confirmed_singletons(singleton_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS wallet_id_index on confirmed_singletons(wallet_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS removed_height_index on confirmed_singletons(removed_height)")


            await conn.execute(
                    "CREATE TABLE IF NOT EXISTS unconfirmed_singletons("
                    "coin_id blob PRIMARY KEY,"
                    " singleton_id blob,"
                    " wallet_id int,"
                    " coin_spend blob)"
                )

            await conn.execute("CREATE INDEX IF NOT EXISTS singleton_id_index on unconfirmed_singletons(singleton_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS wallet_id_index on unconfirmed_singletons(wallet_id)")

        return self

    # rename from save_singleton
    async def add_confirmed_singleton(
        self,
        record: SingletonRecord
    ) -> None:
        singleton_id = get_singleton_id_from_puzzle(record.parent_coinspend.puzzle_reveal)
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                f"INSERT or REPLACE INTO confirmed_singletons ({CONFIRMED_COLS}) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.coin.name().hex(),
                    json.dumps(record.coin.to_json_dict()),
                    singleton_id.hex(),
                    record.wallet_id,
                    bytes(record.parent_coinspend),
                    record.inner_puzzle_hash,
                    record.removed_height,
                    bytes(record.lineage_proof),
                    record.custom_data,
                ),
            )

            # Find and delete matching unconfirmed singleton
            await conn.execute(
                f"DELETE FROM unconfirmed_singletons WHERE singleton_id = ? AND wallet_id = ?",
                (singleton_id.hex(), record.wallet_id),
            )

    async def add_unconfirmed_singleton(self, coin_spend: CoinSpend, wallet_id: uint32) -> None:
        singleton_id = get_singleton_id_from_puzzle(coin_spend.puzzle_reveal)
        coin_id = get_most_recent_singleton_coin_from_coin_spend(coin_spend).name()
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                f"INSERT or REPLACE INTO unconfirmed_singletons ({UNCONFIRMED_COLS}) VALUES(?, ?, ?, ?)",
                (coin_id.hex(), singleton_id.hex(), wallet_id, bytes(coin_spend))
            )

    # TODO: replace with add_confirmed_singleton
    async def add_spend(self, wallet_id: uint32, coin_spend: CoinSpend, block_height: uint32) -> None:
        """Given a coin spend of a singleton, attempt to calculate the child coin and details
        for the new singleton record. Add the new record to the store and remove the old record
        if it exists
        """
        # get singleton_id from puzzle_reveal
        singleton_id = get_singleton_id_from_puzzle(coin_spend.puzzle_reveal)
        if not singleton_id:
            raise ValueError("Coin to add is not a valid singleton")

        coin = get_most_recent_singleton_coin_from_coin_spend(coin_spend)
        inner_puz = get_innerpuzzle_from_puzzle(coin_spend.puzzle_reveal)
        lineage_bytes = coin_spend.solution.to_program().first().as_atom_list()
        lineage_proof = LineageProof(lineage_bytes[0], lineage_bytes[1], int_from_bytes(lineage_bytes[2]))
        # Create and save the new singleton record
        # Remove pending from record table, and create new one for pending coins: coin_id, singleton_id, coin_spend
        new_record = SingletonRecord(
            coin=coin,
            singleton_id=singleton_id,
            wallet_id=wallet_id,
            parent_coinspend=coin_spend,
            inner_puzzle_hash=inner_puz.get_tree_hash(),
            removed_height=0,
            lineage_proof=lineage_proof,
            custom_data=None
        )
        await self.add_confirmed_singleton(new_record)
        # check if coin is in DB and mark deleted if found
        current_record = await self.get_record_by_coin_id(coin_spend.coin.name())
        if current_record:
            self.delete_singleton_by_coin_id(coin_spend.coin.name(), block_height)
        return

    def create_singleton_record_from_coin_spend(self, coin_spend: CoinSpend, wallet_id: uint32) -> SingletonRecord:
        singleton_id = get_singleton_id_from_puzzle(coin_spend.puzzle_reveal)
        if not singleton_id:
            raise ValueError("Coin to add is not a valid singleton")

        coin = get_most_recent_singleton_coin_from_coin_spend(coin_spend)
        inner_puz = get_innerpuzzle_from_puzzle(coin_spend.puzzle_reveal)
        lineage_bytes = coin_spend.solution.to_program().first().as_atom_list()
        lineage_proof = LineageProof(lineage_bytes[0], lineage_bytes[1], int_from_bytes(lineage_bytes[2]))
        return SingletonRecord(
            coin=coin,
            singleton_id=singleton_id,
            wallet_id=wallet_id,
            parent_coinspend=coin_spend,
            inner_puzzle_hash=inner_puz.get_tree_hash(),
            removed_height=0,
            lineage_proof=lineage_proof,
            custom_data=None
        )

    async def confirm_unconfirmed_singleton(self, singleton_id: bytes32) -> None:
        unconfirmed_records = await self.get_unconfirmed_singletons_by_singleton_id(singleton_id)
        if not unconfirmed_records:
            raise ValueError(f"Unconfirmed singleton not found for singleton id: {singleton_id}")
        coin_spend = unconfirmed_records[0][3]
        wallet_id = unconfirmed_records[0][2]
        record = self.create_singleton_record_from_coin_spend(coin_spend, wallet_id)
        await self.add_confirmed_singleton(record)

    async def get_unconfirmed_singleton_by_coin_id(self, coin_id: bytes32) -> List:
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM unconfirmed_singletons WHERE coin_id = ?",
                (coin_id.hex(),),
            )
        if rows:
            row = rows[0]
            return [
                bytes32.from_hexstr(row[0]),
                bytes32.from_hexstr(row[1]),
                row[2],
                CoinSpend.from_bytes(row[3])
            ]

    async def get_unconfirmed_singletons_by_singleton_id(self, singleton_id: bytes32) -> List:
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM unconfirmed_singletons WHERE singleton_id = ?",
                (singleton_id.hex(),),
            )
        if rows:
            return [
                [
                 bytes32.from_hexstr(row[0]),
                 bytes32.from_hexstr(row[1]),
                 row[2],
                 CoinSpend.from_bytes(row[3])
                ] for row in rows
            ]

    def _to_singleton_record(self, row: Row) -> SingletonRecord:
        return SingletonRecord(
            coin=Coin.from_json_dict(json.loads(row[1])),
            singleton_id=bytes32.from_hexstr(row[2]),
            wallet_id=uint32(row[3]),
            parent_coinspend=CoinSpend.from_bytes(row[4]),
            inner_puzzle_hash=bytes32.from_bytes(row[5]),
            removed_height=uint32(row[6]),
            lineage_proof=LineageProof.from_bytes(row[7]),
            custom_data=row[8]
        )

    async def delete_singleton_by_singleton_id(self, singleton_id: bytes32, height: uint32) -> bool:
        """Tries to mark a given singleton as deleted at specific height

        This is due to how re-org works
        Returns `True` if singleton was found and marked deleted or `False` if not."""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove NFT in the users_nfts table
            cursor = await conn.execute(
                "UPDATE confirmed_singletons SET removed_height=? WHERE singleton_id=?",
                (int(height), singleton_id.hex())
            )
            return cursor.rowcount > 0

    async def delete_singleton_by_coin_id(self, coin_id: bytes32, height: uint32) -> bool:
        """Tries to mark a given singleton as deleted at specific height

        This is due to how re-org works
        Returns `True` if singleton was found and marked deleted or `False` if not."""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove NFT in the users_nfts table
            cursor = await conn.execute(
                "UPDATE confirmed_singletons SET removed_height=? WHERE coin_id=?", (int(height), coin_id.hex())
            )
            if cursor.rowcount > 0:
                log.info("Deleted singleton with coin id: %s", coin_id.hex())
                return True
            log.warning("Couldn't find singleton with coin id to delete: %s", coin_id)
            return False

    async def get_records_by_wallet_id(self, wallet_id: int) -> List[SingletonRecord]:
        """
        Retrieves all entries for a wallet ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM confirmed_singletons WHERE wallet_id = ? ORDER BY removed_height",
                (wallet_id,),
            )
        return [self._to_singleton_record(row) for row in rows]

    async def get_record_by_coin_id(self, coin_id: bytes33) -> SingletonRecord:
        """
        Retrieves all entries for a coin ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM confirmed_singletons WHERE coin_id = ?",
                (coin_id.hex(),),
            )
        if rows:
            return self._to_singleton_record(rows[0])
        else:
            return None

    async def get_records_by_singleton_id(self, singleton_id: bytes33) -> SingletonRecord:
        """
        Retrieves all entries for a singleton ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM confirmed_singletons WHERE singleton_id = ? ORDER BY removed_height",
                (singleton_id.hex(),),
            )
        return [self._to_singleton_record(row) for row in rows]


    async def rollback(self, height: int, wallet_id_arg: int) -> None:
        """
        Rollback removes all entries which have entry_height > height passed in. Note that this is not committed to the
        DB until db_wrapper.commit() is called. However it is written to the cache, so it can be fetched with
        get_all_state_transitions.
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM confirmed_singletons WHERE removed_height>? AND wallet_id=?", (height, wallet_id_arg)
            )
            await cursor.close()
