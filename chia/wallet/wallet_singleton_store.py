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

class WalletSingletonStore:
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls: Type[_T_WalletSingletonStore], wrapper: DBWrapper2) -> _T_WalletSingletonStore:
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS singletons("
                    "coin_id blob PRIMARY KEY,"
                    " coin text,"
                    " singleton_id blob,"
                    " wallet_id int,"
                    " parent_coin_spend blob,"
                    " inner_puzzle_hash blob,"
                    " pending tinyint,"
                    " removed_height int,"
                    " lineage_proof blob,"
                    " custom_data blob)"
                )
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS removed_height_index on singletons(removed_height)")

        return self

    async def save_singleton(
        self,
        record: SingletonRecord
    ) -> None:
        singleton_id = singleton.get_singleton_id_from_puzzle(record.parent_coinspend.puzzle_reveal)
        pending_int = 0
        if record.pending:
            pending_int = 1
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            columns = (
                "coin_id, coin, singleton_id, wallet_id, parent_coin_spend, inner_puzzle_hash, pending, removed_height, "
                "lineage_proof, custom_data"
            )
            await conn.execute(
                f"INSERT or REPLACE INTO singletons ({columns}) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.coin.name().hex(),
                    json.dumps(record.coin.to_json_dict()),
                    singleton_id.hex(),
                    record.wallet_id,
                    bytes(record.parent_coinspend),
                    record.inner_puzzle_hash,
                    pending_int,
                    record.removed_height,
                    bytes(record.lineage_proof),
                    record.custom_data,
                ),
            )

    # async def add_spend(
    #     self,
    #     wallet_id: int,
    #     spend: CoinSpend,
    #     height: uint32,
    # ) -> None:
    #     """
    #     Appends (or replaces) entries in the DB. The new list must be at least as long as the existing list, and the
    #     parent of the first spend must already be present in the DB. Note that this is not committed to the DB
    #     until db_wrapper.commit() is called. However it is written to the cache, so it can be fetched with
    #     get_all_state_transitions.
    #     """
    #     async with self.db_wrapper.writer_maybe_transaction() as conn:
    #         # find the most recent transition in wallet_id
    #         rows = list(
    #             await conn.execute_fetchall(
    #                 "SELECT transition_index, height, coin_spend "
    #                 "FROM pool_state_transitions "
    #                 "WHERE wallet_id=? "
    #                 "ORDER BY transition_index DESC "
    #                 "LIMIT 1",
    #                 (wallet_id,),
    #             )
    #         )
    #         serialized_spend = bytes(spend)
    #         if len(rows) == 0:
    #             transition_index = 0
    #         else:
    #             existing = list(
    #                 await conn.execute_fetchall(
    #                     "SELECT COUNT(*) "
    #                     "FROM pool_state_transitions "
    #                     "WHERE wallet_id=? AND height=? AND coin_spend=?",
    #                     (wallet_id, height, serialized_spend),
    #                 )
    #             )
    #             if existing[0][0] != 0:
    #                 # we already have this transition in the DB
    #                 return
    #
    #             row = rows[0]
    #             if height < row[1]:
    #                 raise ValueError("Height cannot go down")
    #             prev = CoinSpend.from_bytes(row[2])
    #             if spend.coin.parent_coin_info != prev.coin.name():
    #                 raise ValueError("New spend does not extend")
    #             transition_index = row[0]
    #
    #         cursor = await conn.execute(
    #             "INSERT OR IGNORE INTO pool_state_transitions VALUES (?, ?, ?, ?)",
    #             (
    #                 transition_index + 1,
    #                 wallet_id,
    #                 height,
    #                 serialized_spend,
    #             ),
    #         )
    #         await cursor.close()

    def process_row(self, row: List[Any]) -> List[Any]:
        record = SingletonRecord(
            coin=Coin.from_json_dict(json.loads(row[1])),
            singleton_id=bytes32.from_hexstr(row[2]),
            wallet_id=uint32(row[3]),
            parent_coinspend=CoinSpend.from_bytes(row[4]),
            inner_puzzle_hash=bytes32.from_bytes(row[5]),  #  inner puz hash
            pending=True if row[6] == 1 else False,
            removed_height=uint32(row[7]),
            lineage_proof=LineageProof.from_bytes(row[8]),
            custom_data=row[9]
        )

    async def delete_singleton_by_singleton_id(self, singleton_id: bytes32, height: uint32) -> bool:
        """Tries to mark a given singleton as deleted at specific height

        This is due to how re-org works
        Returns `True` if singleton was found and marked deleted or `False` if not."""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove NFT in the users_nfts table
            cursor = await conn.execute(
                "UPDATE singletons SET removed_height=? WHERE singleton_id=?",
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
                "UPDATE singletons SET removed_height=? WHERE coin_id=?", (int(height), coin_id.hex())
            )
            if cursor.rowcount > 0:
                log.info("Deleted singleton with coin id: %s", coin_id.hex())
                return True
            log.warning("Couldn't find singleton with coin id to delete: %s", coin_id)
            return False


    async def update_pending_transaction(self, coin_id: bytes32, pending: bool) -> bool:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            c = await conn.execute(
                "UPDATE singletons SET pending=? WHERE coin_id = ?",
                (pending, coin_id.hex()),
            )
            return c.rowcount > 0


    async def get_records_by_wallet_id(self, wallet_id: int) -> List[SingletonRecord]:
        """
        Retrieves all entries for a wallet ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM singletons WHERE wallet_id = ? ORDER BY removed_height",
                (wallet_id,),
            )
        return [self._to_singleton_record(row) for row in rows]

    async def get_record_by_coin_id(self, coin_id: bytes33) -> SingletonRecord:
        """
        Retrieves all entries for a coin ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM singletons WHERE coin_id = ?",
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
                "SELECT * FROM singletons WHERE singleton_id = ? ORDER BY removed_height",
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
                "DELETE FROM singletons WHERE removed_height>? AND wallet_id=?", (height, wallet_id_arg)
            )
            await cursor.close()
