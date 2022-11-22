from __future__ import annotations

import logging
from typing import List, Tuple

from chia.types.coin_spend import CoinSpend
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32

log = logging.getLogger(__name__)


class WalletPoolStore:
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, wrapper: DBWrapper2):
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS pool_state_transitions("
                " transition_index integer,"
                " wallet_id integer,"
                " height bigint,"
                " coin_spend blob,"
                " PRIMARY KEY(transition_index, wallet_id))"
            )

        return self

    async def add_spend(
        self,
        wallet_id: int,
        spend: CoinSpend,
        height: uint32,
    ) -> None:
        """
        Appends (or replaces) entries in the DB. The new list must be at least as long as the existing list, and the
        parent of the first spend must already be present in the DB. Note that this is not committed to the DB
        until db_wrapper.commit() is called. However it is written to the cache, so it can be fetched with
        get_all_state_transitions.
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # find the most recent transition in wallet_id
            rows = list(
                await conn.execute_fetchall(
                    "SELECT transition_index, height, coin_spend "
                    "FROM pool_state_transitions "
                    "WHERE wallet_id=? "
                    "ORDER BY transition_index DESC "
                    "LIMIT 1",
                    (wallet_id,),
                )
            )
            serialized_spend = bytes(spend)
            if len(rows) == 0:
                transition_index = 0
            else:
                existing = list(
                    await conn.execute_fetchall(
                        "SELECT COUNT(*) "
                        "FROM pool_state_transitions "
                        "WHERE wallet_id=? AND height=? AND coin_spend=?",
                        (wallet_id, height, serialized_spend),
                    )
                )
                if existing[0][0] != 0:
                    # we already have this transition in the DB
                    return

                row = rows[0]
                if height < row[1]:
                    raise ValueError("Height cannot go down")
                prev = CoinSpend.from_bytes(row[2])
                if spend.coin.parent_coin_info != prev.coin.name():
                    raise ValueError("New spend does not extend")
                transition_index = row[0]

            cursor = await conn.execute(
                "INSERT OR IGNORE INTO pool_state_transitions VALUES (?, ?, ?, ?)",
                (
                    transition_index + 1,
                    wallet_id,
                    height,
                    serialized_spend,
                ),
            )
            await cursor.close()

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

    async def rollback(self, height: int, wallet_id_arg: int) -> None:
        """
        Rollback removes all entries which have entry_height > height passed in. Note that this is not committed to the
        DB until db_wrapper.commit() is called. However it is written to the cache, so it can be fetched with
        get_all_state_transitions.
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM pool_state_transitions WHERE height>? AND wallet_id=?", (height, wallet_id_arg)
            )
            await cursor.close()
