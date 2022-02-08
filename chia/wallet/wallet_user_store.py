from typing import List, Optional

from databases import Database

from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_info import WalletInfo
from chia.util import dialect_utils


class WalletUserStore:
    """
    WalletUserStore keeps track of all user created wallets and necessary smart-contract data
    """

    db_connection: Database
    cache_size: uint32
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        self.db_wrapper = db_wrapper
        self.db_connection = db_wrapper.db
        async with self.db_connection.connection() as connection:
            async with connection.transaction():
                await self.db_connection.execute(
                    (
                        "CREATE TABLE IF NOT EXISTS users_wallets("
                        f"id INTEGER PRIMARY KEY {dialect_utils.clause('AUTOINCREMENT', self.db_connection.url.dialect)},"
                        f" name {dialect_utils.data_type('text-as-index', self.db_connection.url.dialect)},"
                        " wallet_type int,"
                        f" data {dialect_utils.data_type('text-as-index', self.db_connection.url.dialect)})"
                    )
                )

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'name', 'users_wallets', ['name'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'type', 'users_wallets', ['wallet_type'])

                await dialect_utils.create_index_if_not_exists(self.db_connection, 'data', 'users_wallets', ['data'])

                await self.init_wallet()
        return self

    async def init_wallet(self):
        all_wallets = await self.get_all_wallet_info_entries()
        if len(all_wallets) == 0:
            await self.create_wallet("Chia Wallet", WalletType.STANDARD_WALLET, "")

    async def _clear_database(self):
        await self.db_connection.execute("DELETE FROM users_wallets")

    async def create_wallet(
        self, name: str, wallet_type: int, data: str, id: Optional[int] = None, in_transaction=False
    ) -> Optional[WalletInfo]:

        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            if id is None:
                await self.db_connection.execute(
                    "INSERT INTO users_wallets(name, wallet_type, data) VALUES(:name, :wallet_type, :data)",
                    {"name":  name, "wallet_type":  int(wallet_type), "data":  data},
                )
            else:
                await self.db_connection.execute(
                    "INSERT INTO users_wallets(id, name, wallet_type, data) VALUES(:id, :name, :wallet_type, :data)",
                    {"id": int(id), "name":  name, "wallet_type":  int(wallet_type), "data":  data},
                )
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

        return await self.get_last_wallet()

    async def delete_wallet(self, id: int, in_transaction: bool):
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            await self.db_connection.execute(f"DELETE FROM users_wallets where id={int(id)}")
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def update_wallet(self, wallet_info: WalletInfo, in_transaction):
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            await self.db_connection.execute(
                "INSERT or REPLACE INTO users_wallets VALUES(:id, :name, :wallet_type, :data)",
                {
                    "id": int(wallet_info.id),
                    "name": wallet_info.name,
                    "wallet_type": int(wallet_info.type),
                    "data": wallet_info.data,
                }
            )
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def get_last_wallet(self) -> Optional[WalletInfo]:
        row = await self.db_connection.fetch_one("SELECT MAX(id) FROM users_wallets;")

        if row is None:
            return None

        return await self.get_wallet_by_id(row[0])

    async def get_all_wallet_info_entries(self) -> List[WalletInfo]:
        """
        Return a set containing all wallets
        """

        rows = await self.db_connection.fetch_all("SELECT * from users_wallets")
        result = []

        for row in rows:
            result.append(WalletInfo(row[0], row[1], row[2], row[3]))

        return result

    async def get_wallet_by_id(self, id: int) -> Optional[WalletInfo]:
        """
        Return a wallet by id
        """

        row = await self.db_connection.fetch_one("SELECT * from users_wallets WHERE id=:id", {"id": int(id)})

        if row is None:
            return None

        return WalletInfo(row[0], row[1], row[2], row[3])
