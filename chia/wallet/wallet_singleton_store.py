from __future__ import annotations
import json
import logging
from typing import List, Tuple, Optional, Any
from chia.wallet import singleton
from chia.types.coin_spend import CoinSpend
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32

log = logging.getLogger(__name__)


class WalletSingletonStore:
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, wrapper: DBWrapper2):
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS singleton_records("
                    "coin_id blob PRIMARY KEY,"
                    " coin text,"
                    " singleton_id blob,"
                    " parent_coin_spend blob,"
                    " inner_puzzle_hash blob,"
                    " pending tinyint,"
                    " removed_height int,"
                    " lineage_proof blob,"
                    " custom_data blob)"
                )
            )

        # This table allows us to have multiple interested wallets in a single singleton
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS singleton_wallet_ids("
                    "coin_id blob,"
                    " wallet_id int)"
                )
            )

        return self

    async def save_singleton(
        self,
        coin: Coin,
        parent_coinspend: CoinSpend,
        wallet_ids: List[uint32],
        inner_puzzle_hash: Optional[bytes32],
        lineage_proof: Optional[bytes32],
        pending: bool,
        removed_height: int,
        custom_data: Optional[Any],
    ) -> None:
        singleton_id = singleton.get_singleton_id_from_puzzle(Program.to(bytes(parent_coinspend.puzzle)))
        pending_int = 0
        if pending:
            pending = 1
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            columns = (
                "coin_id, coin, singleton_id, parent_coin_spend, inner_puzzle_hash, pending, removed_height, "
                "lineage_proof, custom_data"
            )
            await conn.execute(
                f"INSERT or REPLACE INTO singleton_records ({columns}) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    coin.name().hex(),
                    json.dumps(coin.to_json_dict()),
                    singleton_id.hex(),
                    bytes(parent_coinspend),
                    inner_puzzle_hash,
                    pending_int,
                    removed_height,
                    json.dumps(lineage_proof.to_json_dict()),
                    custom_data,
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

    async def get_spends_for_wallet(self, wallet_id: int) -> List[Tuple[uint32, CoinSpend]]:
        """
        Retrieves all entries for a wallet ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT height, coin_spend FROM pool_state_transitions WHERE wallet_id=? ORDER BY transition_index",
                (wallet_id,),
            )
        return [(uint32(row[0]), CoinSpend.from_bytes(row[1])) for row in rows]

    async def rollback(self, height: int, singleton_id_arg: int) -> None:
        """
        Rollback removes all entries which have entry_height > height passed in. Note that this is not committed to the
        DB until db_wrapper.commit() is called. However it is written to the cache, so it can be fetched with
        get_all_state_transitions.
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM singleton_records WHERE removed_height>? AND wallet_id=?", (height, wallet_id_arg)
            )
            await cursor.close()
