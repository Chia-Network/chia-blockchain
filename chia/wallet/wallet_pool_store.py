from typing import List, Tuple

import aiosqlite

from chia.types.coin_solution import CoinSolution
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32


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
            "CREATE TABLE IF NOT EXISTS pool_state_transitions(index int, wallet_id int "
            f"height bigint, coin_name text, coin_spend blob, PRIMARY KEY(index, wallet_id)"
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
        spend: CoinSolution,
        height: uint32,
    ) -> None:
        all_state_transitions = await self.get_all_state_transition(wallet_id)

        # Idempotent
        if spend in [cs for _, _, cs in all_state_transitions]:
            return None

        if len(all_state_transitions) > 0:
            index: int = all_state_transitions[0][0] + 1
        else:
            index = 0
        cursor = await self.db_connection.execute(
            "INSERT INTO pool_state_transitions VALUES (?, ?, ?, ?)",
            (index, height, spend.coin.name(), bytes(spend)),
        )
        await cursor.close()

    async def get_all_state_transition(self, wallet_id: int) -> List[Tuple[int, uint32, CoinSolution]]:
        cursor = await self.db_connection.execute(
            "SELECT * FROM pool_state_transitions WHERE wallet_id=? ORDER BY index", (wallet_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        state_transitions: List[Tuple[int, uint32, CoinSolution]] = []
        max_index = -1
        for row in rows:
            index, wallet_id_db, height, coin_name, coin_spend = row
            if wallet_id_db == wallet_id:
                assert index == max_index + 1
                max_index = index
                state_transitions.append((index, height, CoinSolution.from_bytes(coin_spend)))

        return state_transitions

    async def rollback(self, height: uint32) -> None:
        cursor = await self.db_connection.execute("DELETE FROM pool_state_transitions WHERE height>?", (height,))
        await cursor.close()
