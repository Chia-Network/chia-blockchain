from typing import Optional

import aiosqlite
from src.util.ints import uint32
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_action import WalletAction


class WalletActionStore:
    """
    WalletActionStore keeps track of all wallet actions that require persistence.
    Used by Colored coins, Atomic swaps, Rate Limited, and Authorized payee wallets
    """

    db_connection: aiosqlite.Connection
    cache_size: uint32

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        self.db_connection = connection

        await self.db_connection.execute(
            (
                f"CREATE TABLE IF NOT EXISTS action_queue("
                f"id INTEGER PRIMARY KEY AUTOINCREMENT,"
                f" name text,"
                f" wallet_id int,"
                f" wallet_type int,"
                f" wallet_callback text,"
                f" done int,"
                f" data text)"
            )
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS name on action_queue(name)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS wallet_id on action_queue(wallet_id)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS wallet_type on action_queue(wallet_type)"
        )

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM action_queue")
        await cursor.close()
        await self.db_connection.commit()

    async def get_wallet_action(self, id: int) -> Optional[WalletAction]:
        """
        Return a wallet action by id
        """

        cursor = await self.db_connection.execute(
            "SELECT * from action_queue WHERE id=?", (id,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        return WalletAction(
            row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6]
        )

    async def create_action(
        self,
        name: str,
        wallet_id: int,
        type: WalletType,
        callback: str,
        done: bool,
        data: str,
    ):
        """
        Creates Wallet Action
        """
        cursor = await self.db_connection.execute(
            "INSERT INTO action_queue VALUES(?, ?, ?, ?, ?, ?)",
            (None, name, wallet_id, type.value, callback, done, data),
        )
        await cursor.close()
        await self.db_connection.commit()

    async def action_done(self, action_id: int):
        """
        Marks action as done
        """
        action: Optional[WalletAction] = await self.get_wallet_action(action_id)
        assert action is not None

        cursor = await self.db_connection.execute(
            "Replace INTO action_queue VALUES(?, ?, ?, ?, ?, ?)",
            (
                action.id,
                action.name,
                action.wallet_id,
                action.type.value,
                action.wallet_callback,
                True,
                action.data,
            ),
        )

        await cursor.close()
        await self.db_connection.commit()

    async def get_not_executed_action(self,) -> Optional[WalletAction]:
        """
        Return a wallet action by id
        """

        cursor = await self.db_connection.execute(
            "SELECT * from action_queue WHERE id=?", (id,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        return WalletAction(
            row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6]
        )
