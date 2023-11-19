from __future__ import annotations

from typing import List, Optional

from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_info import WalletInfo


class WalletUserStore:
    """
    WalletUserStore keeps track of all user created wallets and necessary smart-contract data
    """

    cache_size: uint32
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2):
        self = cls()

        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS users_wallets("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " name text,"
                " wallet_type int,"
                " data text)"
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS name on users_wallets(name)")

            await conn.execute("CREATE INDEX IF NOT EXISTS type on users_wallets(wallet_type)")

            await conn.execute("CREATE INDEX IF NOT EXISTS data on users_wallets(data)")

        await self.init_wallet()
        return self

    async def init_wallet(self):
        all_wallets = await self.get_all_wallet_info_entries()
        if len(all_wallets) == 0:
            await self.create_wallet("Chia Wallet", WalletType.STANDARD_WALLET, "")

    async def create_wallet(
        self,
        name: str,
        wallet_type: int,
        data: str,
        id: Optional[int] = None,
    ) -> WalletInfo:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO users_wallets VALUES(?, ?, ?, ?)",
                (id, name, wallet_type, data),
            )
            await cursor.close()
            wallet = await self.get_last_wallet()
            if wallet is None:
                raise ValueError("Failed to get the just-created wallet")

        return wallet

    async def delete_wallet(self, id: int):
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM users_wallets where id=?", (id,))).close()

    async def update_wallet(self, wallet_info: WalletInfo):
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT or REPLACE INTO users_wallets VALUES(?, ?, ?, ?)",
                (
                    wallet_info.id,
                    wallet_info.name,
                    wallet_info.type,
                    wallet_info.data,
                ),
            )
            await cursor.close()

    async def get_last_wallet(self) -> Optional[WalletInfo]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, "SELECT MAX(id) FROM users_wallets")

        return None if row is None else await self.get_wallet_by_id(row[0])

    async def get_all_wallet_info_entries(self, wallet_type: Optional[WalletType] = None) -> List[WalletInfo]:
        """
        Return a set containing all wallets, optionally with a specific WalletType
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            if wallet_type is None:
                rows = await conn.execute_fetchall("SELECT * from users_wallets")
            else:
                rows = await conn.execute_fetchall(
                    "SELECT * from users_wallets WHERE wallet_type=?", (wallet_type.value,)
                )
            return [WalletInfo(row[0], row[1], row[2], row[3]) for row in rows]

    async def get_wallet_by_id(self, id: int) -> Optional[WalletInfo]:
        """
        Return a wallet by id
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, "SELECT * from users_wallets WHERE id=?", (id,))

        return None if row is None else WalletInfo(row[0], row[1], row[2], row[3])
