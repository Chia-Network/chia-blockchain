from __future__ import annotations

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.util.db_wrapper import DBWrapper2


class RemoteCoinStore:
    """Persists coin IDs that a RemoteWallet is tracking."""

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, wrapper: DBWrapper2) -> RemoteCoinStore:
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS remote_coins(coin_id blob PRIMARY KEY, wallet_id integer NOT NULL)"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS remote_coins_wallet_id ON remote_coins(wallet_id)")

        return self

    async def add_coin_ids(self, coin_ids: list[bytes32], wallet_id: uint32) -> int:
        """Insert coin IDs for *wallet_id*, ignoring duplicates. Returns the number of newly inserted rows."""
        if len(coin_ids) == 0:
            return 0

        added = 0
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            for coin_id in coin_ids:
                result = await conn.execute(
                    "INSERT OR IGNORE INTO remote_coins (coin_id, wallet_id) VALUES (?, ?)",
                    (bytes(coin_id), int(wallet_id)),
                )
                added += result.rowcount
        return added

    async def get_coin_ids(self, wallet_id: uint32) -> list[bytes32]:
        """Return all coin IDs registered for a specific wallet."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT coin_id FROM remote_coins WHERE wallet_id = ?",
                (int(wallet_id),),
            )
            rows = await cursor.fetchall()
        return [bytes32(row[0]) for row in rows]
