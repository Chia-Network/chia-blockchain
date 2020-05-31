from typing import Optional, List

import aiosqlite
from src.util.ints import uint32
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_info import WalletInfo


class WalletUserStore:
    """
    WalletUserStore keeps track of all user created wallets and necessary smart-contract data
    """

    db_connection: aiosqlite.Connection
    cache_size: uint32

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        self.db_connection = connection

        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS users_wallets("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " name text,"
                " wallet_type int,"
                " data text)"
            )
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS name on users_wallets(name)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS type on users_wallets(wallet_type)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS data on users_wallets(data)"
        )

        await self.db_connection.commit()
        await self.init_wallet()
        return self

    async def init_wallet(self):
        all_wallets = await self.get_all_wallets()
        if len(all_wallets) == 0:
            await self.create_wallet("Chia Wallet", WalletType.STANDARD_WALLET, "")

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM users_wallets")
        await cursor.close()
        await self.db_connection.commit()

    async def create_wallet(
        self, name: str, wallet_type: WalletType, data: str
    ) -> Optional[WalletInfo]:
        cursor = await self.db_connection.execute(
            "INSERT INTO users_wallets VALUES(?, ?, ?, ?)",
            (None, name, wallet_type.value, data),
        )
        await cursor.close()
        await self.db_connection.commit()
        return await self.get_last_wallet()

    async def delete_wallet(self, id: int):
        cursor = await self.db_connection.execute(f"DELETE FROM users_wallets where id={id}")
        await cursor.close()
        await self.db_connection.commit()

    async def update_wallet(self, wallet_info: WalletInfo):
        cursor = await self.db_connection.execute(
            "INSERT or REPLACE INTO users_wallets VALUES(?, ?, ?, ?)",
            (
                wallet_info.id,
                wallet_info.name,
                wallet_info.type.value,
                wallet_info.data,
            ),
        )
        await cursor.close()
        await self.db_connection.commit()

    async def get_last_wallet(self) -> Optional[WalletInfo]:
        cursor = await self.db_connection.execute("SELECT MAX(id) FROM users_wallets;")
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        return await self.get_wallet_by_id(row[0])

    async def get_all_wallets(self) -> List[WalletInfo]:
        """
        Return a set containing all wallets
        """

        cursor = await self.db_connection.execute("SELECT * from users_wallets")
        rows = await cursor.fetchall()
        await cursor.close()
        result = []

        for row in rows:
            result.append(WalletInfo(row[0], row[1], WalletType(row[2]), row[3]))

        return result

    async def get_wallet_by_id(self, id: int) -> Optional[WalletInfo]:
        """
        Return a wallet by id
        """

        cursor = await self.db_connection.execute(
            "SELECT * from users_wallets WHERE id=?", (id,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        return WalletInfo(row[0], row[1], WalletType(row[2]), row[3])
