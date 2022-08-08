from typing import List, Optional

from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action import WalletAction


class WalletActionStore:
    """
    WalletActionStore keeps track of all wallet actions that require persistence.
    Used by CATs, Atomic swaps, Rate Limited, and Authorized payee wallets
    """

    cache_size: uint32
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2):
        self = cls()
        self.db_wrapper = db_wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
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

            await conn.execute("CREATE INDEX IF NOT EXISTS action_queue_name on action_queue(name)")

            await conn.execute("CREATE INDEX IF NOT EXISTS action_queue_wallet_id on action_queue(wallet_id)")

            await conn.execute("CREATE INDEX IF NOT EXISTS action_queue_wallet_type on action_queue(wallet_type)")
        return self

    async def get_wallet_action(self, id: int) -> Optional[WalletAction]:
        """
        Return a wallet action by id
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from action_queue WHERE id=?", (id,))
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return WalletAction(row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6])

    async def create_action(self, name: str, wallet_id: int, type: int, callback: str, done: bool, data: str):
        """
        Creates Wallet Action
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO action_queue VALUES(?, ?, ?, ?, ?, ?, ?)",
                (None, name, wallet_id, type, callback, done, data),
            )
            await cursor.close()

    async def get_all_pending_actions(self) -> List[WalletAction]:
        """
        Returns list of all pending action
        """
        result: List[WalletAction] = []
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from action_queue WHERE done=?", (0,))
            rows = await cursor.fetchall()
            await cursor.close()

        if rows is None:
            return result

        for row in rows:
            action = WalletAction(row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6])
            result.append(action)

        return result

    async def get_action_by_id(self, id) -> Optional[WalletAction]:
        """
        Return a wallet action by id
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from action_queue WHERE id=?", (id,))
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return WalletAction(row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6])
