from typing import Optional, List

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
                "CREATE TABLE IF NOT EXISTS action_queue("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " name text,"
                " wallet_id int,"
                " wallet_type int,"
                " wallet_callback text,"
                " done int,"
                " data text)"
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
            "INSERT INTO action_queue VALUES(?, ?, ?, ?, ?, ?, ?)",
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
            "Replace INTO action_queue VALUES(?, ?, ?, ?, ?, ?, ?)",
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

    async def get_all_pending_actions(self) -> List[WalletAction]:
        """
        Returns list of all pending action
        """
        result: List[WalletAction] = []
        cursor = await self.db_connection.execute(
            "SELECT * from action_queue WHERE done=?", (0,)
        )
        rows = await cursor.fetchall()
        await cursor.close()

        if rows is None:
            return result

        for row in rows:
            action = WalletAction(
                row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6]
            )
            result.append(action)

        return result

    async def get_action_by_id(self, id) -> Optional[WalletAction]:
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
