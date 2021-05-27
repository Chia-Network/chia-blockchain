import logging
from typing import List, Tuple

import aiosqlite

from chia.types.coin_solution import CoinSolution
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32

log = logging.getLogger(__name__)


class WalletPoolStore:
    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, wrapper: DBWrapper):
        self = cls()

        self.db_connection = wrapper.db
        self.db_wrapper = wrapper
        await self.db_connection.execute("pragma journal_mode=wal")
        await self.db_connection.execute("pragma synchronous=2")

        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS pool_state_transitions(transition_index integer, wallet_id integer, "
            f"height bigint, coin_name text, coin_spend blob, PRIMARY KEY(transition_index, wallet_id))"
        )
        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM interested_coins")
        await cursor.close()
        await self.db_connection.commit()

    async def apply_state(
        self,
        wallet_id: int,
        spends: List[CoinSolution],
        height: uint32,
    ) -> None:
        all_state_transitions = await self.get_all_state_transitions(wallet_id)

        # TODO: make this method idempotent
        if len(all_state_transitions) > 0:
            index: int = all_state_transitions[-1][0] + 1
        else:
            index = 0
        for i in range(len(spends)):
            spend = spends[i]
            cursor = await self.db_connection.execute(
                "INSERT INTO pool_state_transitions VALUES (?, ?, ?, ?, ?)",
                (index + i, wallet_id, height, spend.coin.name().hex(), bytes(spend)),
            )
            await cursor.close()

    async def get_all_state_transitions(self, wallet_id: int) -> List[Tuple[int, uint32, CoinSolution]]:
        cursor = await self.db_connection.execute("SELECT * FROM pool_state_transitions")
        rows = await cursor.fetchall()
        await cursor.close()

        log.info(f"All rows: {rows}")

        cursor = await self.db_connection.execute(
            "SELECT * FROM pool_state_transitions WHERE wallet_id=? ORDER BY transition_index", (wallet_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        state_transitions: List[Tuple[int, uint32, CoinSolution]] = []
        max_index = -1
        for row in rows:
            index, wallet_id_db, height, _, coin_spend = row
            if wallet_id_db == wallet_id:
                assert index == max_index + 1
                max_index = index
                state_transitions.append((index, height, CoinSolution.from_bytes(coin_spend)))

        return state_transitions

    async def rollback(self, height: int) -> None:
        cursor = await self.db_connection.execute("DELETE FROM pool_state_transitions WHERE height>?", (height,))
        await cursor.close()
