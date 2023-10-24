from __future__ import annotations

from typing import List, Optional, Tuple

from chia_rs import CoinState

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32


class WalletRetryStore:
    """
    Persistent coin states that we have received but failed to add
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> WalletRetryStore:
        self = cls()
        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS retry_store("
                " coin_state blob PRIMARY KEY,"
                " peer blob,"
                " fork_height int)"
            )

        return self

    async def get_all_states_to_retry(self) -> List[Tuple[CoinState, bytes32, uint32]]:
        """
        Return all states that were failed to sync
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall("SELECT * from retry_store")

        return [(CoinState.from_bytes(row[0]), bytes32(row[1]), uint32(row[2])) for row in rows]

    async def add_state(self, state: CoinState, peer_id: bytes32, fork_height: Optional[uint32]) -> None:
        """
        Adds object to key val store. Obj MUST support __bytes__ and bytes() methods.
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO retry_store VALUES(?, ?, ?)",
                (bytes(state), peer_id, 0 if fork_height is None else fork_height),
            )
            await cursor.close()

    async def remove_state(self, state: CoinState) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute("DELETE FROM retry_store where coin_state=?", (bytes(state),))
            await cursor.close()

    async def rollback_to_block(self, height: int) -> None:
        """
        Delete all ignored states above a certain height
        :param height: Reorg height
        :return None:
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "DELETE from retry_store WHERE fork_height>?",
                (height,),
            )
            await cursor.close()
