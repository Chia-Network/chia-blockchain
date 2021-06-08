import logging
from typing import List, Tuple, Dict, Optional

import aiosqlite

from chia.types.coin_solution import CoinSolution
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32

log = logging.getLogger(__name__)


class WalletPoolStore:
    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper
    _state_transitions_cache: Dict[int, List[Tuple[uint32, CoinSolution]]]

    @classmethod
    async def create(cls, wrapper: DBWrapper):
        self = cls()

        self.db_connection = wrapper.db
        self.db_wrapper = wrapper
        await self.db_connection.execute("pragma journal_mode=wal")
        await self.db_connection.execute("pragma synchronous=2")

        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS pool_state_transitions(transition_index integer, wallet_id integer, "
            "height bigint, coin_spend blob, PRIMARY KEY(transition_index, wallet_id))"
        )
        await self.db_connection.commit()
        await self.rebuild_cache()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM interested_coins")
        await cursor.close()
        await self.db_connection.commit()

    async def add_spend(
        self,
        wallet_id: int,
        spend: CoinSolution,
        height: uint32,
    ) -> None:
        """
        Appends (or replaces) entries in the DB. The new list must be at least as long as the existing list, and the
        parent of the first spend must already be present in the DB. Note that this is not committed to the DB
        until db_wrapper.commit() is called. However it is written to the cache, so it can be fetched with
        get_all_state_transitions.
        """
        if wallet_id not in self._state_transitions_cache:
            self._state_transitions_cache[wallet_id] = []
        all_state_transitions: List[Tuple[uint32, CoinSolution]] = self.get_spends_for_wallet(wallet_id)

        if (height, spend) in all_state_transitions:
            return

        if len(all_state_transitions) > 0:
            if height < all_state_transitions[-1][0]:
                raise ValueError("Height cannot go down")
            if spend.coin.parent_coin_info != all_state_transitions[-1][1].coin.name():
                raise ValueError("New spend does not extend")

        all_state_transitions.append((height, spend))

        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO pool_state_transitions VALUES (?, ?, ?, ?)",
            (
                len(all_state_transitions) - 1,
                wallet_id,
                height,
                bytes(spend),
            ),
        )
        await cursor.close()

    def get_spends_for_wallet(self, wallet_id: int) -> List[Tuple[uint32, CoinSolution]]:
        """
        Retrieves all entries for a wallet ID from the cache, works even if commit is not called yet.
        """
        return self._state_transitions_cache.get(wallet_id, [])

    async def rebuild_cache(self) -> None:
        """
        This resets the cache, and loads all entries from the DB. Any entries in the cache that were not committed
        are removed. This can happen if a state transition in wallet_blockchain fails.
        """
        cursor = await self.db_connection.execute("SELECT * FROM pool_state_transitions ORDER BY transition_index")
        rows = await cursor.fetchall()
        await cursor.close()
        self._state_transitions_cache = {}
        for row in rows:
            _, wallet_id, height, coin_solution_bytes = row
            coin_solution: CoinSolution = CoinSolution.from_bytes(coin_solution_bytes)
            if wallet_id not in self._state_transitions_cache:
                self._state_transitions_cache[wallet_id] = []
            self._state_transitions_cache[wallet_id].append((height, coin_solution))

    async def rollback(self, height: int, wallet_id_arg: int) -> None:
        """
        Rollback removes all entries which have entry_height > height passed in. Note that this is not committed to the
        DB until db_wrapper.commit() is called. However it is written to the cache, so it can be fetched with
        get_all_state_transitions.
        """
        for wallet_id, items in self._state_transitions_cache.items():
            remove_index_start: Optional[int] = None
            for i, (item_block_height, _) in enumerate(items):
                if item_block_height > height and wallet_id == wallet_id_arg:
                    remove_index_start = i
                    break
            if remove_index_start is not None:
                del items[remove_index_start:]
        cursor = await self.db_connection.execute(
            "DELETE FROM pool_state_transitions WHERE height>? AND wallet_id=?", (height, wallet_id_arg)
        )
        await cursor.close()
