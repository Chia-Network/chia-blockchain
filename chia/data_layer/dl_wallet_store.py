from typing import List, Optional

import aiosqlite

from chia.data_layer.data_layer_wallet import SingletonRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_info import WalletInfo


class DataLayerStore:
    """
    WalletUserStore keeps track of all user created wallets and necessary smart-contract data
    """

    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        self.db_wrapper = db_wrapper
        self.db_connection = db_wrapper.db
        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS singleton_records("
                "coin_id blob PRIMARY KEY,"
                " launcher_id blob,"
                " root blob,"
                " confirmed tinyint,"
                " confirmed_at_height int,"
                " proof blob,"
                " generation int)"  # This first singleton will be 0, then 1, and so on.  This is handled by the DB.
            )
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS coin_id on singleton_records(coin_id)")
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS launcher_id on singleton_records(launcher_id)")
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS root on singleton_records(root)")
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS confirmed_at_height on singleton_records(root)")

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM singleton_records")
        await cursor.close()
        await self.db_connection.commit()

    def _row_to_singleton_record(self, row) -> SingletonRecord:
        return SingletonRecord(
            bytes32(row[0]),
            bytes32(row[1]),
            bytes32(row[2]),
            bool(row[3]),
            uint32(row[4]),
            None if row[5] == b"" else LineageProof.from_bytes(row[5]),
        )

    async def get_singleton_generation_count(self, launcher_id: bytes32) -> int:
        """
        Count the number of generations of a singleton wit a specific launcher ID.
        """
        cursor = await self.db_connection.execute(
            "SELECT COUNT(*) FROM singleton_records where launcher_id=?", (launcher_id,)
        )
        count_result = await cursor.fetchone()
        if count_result is not None:
            count = count_result[0]
        else:
            count = 0
        await cursor.close()
        return count

    async def add_singleton_record(self, record: SingletonRecord, in_transaction: bool) -> None:
        """
        Store SingletonRecord in DB.
        """

        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            count: int = self.get_singleton_generation_count(record.launcher_id)
            cursor = await self.db_connection.execute(
                "INSERT OR REPLACE INTO singleton_records VALUES(?, ?, ?, ?, ?, ?)",
                (
                    record.coin_id,
                    record.launcher_id,
                    record.root,
                    int(record.confirmed),
                    record.confirmed_at_height,
                    b"" if record.lineage_proof is None else bytes(record.lineage_proof),
                    count,
                ),
            )
            await cursor.close()
            if not in_transaction:
                await self.db_connection.commit()
        except BaseException:
            if not in_transaction:
                # await self.rebuild_tx_cache()
                pass
            raise
        finally:
            if not in_transaction:
                self.db_wrapper.lock.release()

    async def get_all_singletons_for_launcher(self, launcher_id: bytes32) -> List[SingletonRecord]:
        """
        Returns all stored transactions.
        """
        cursor = await self.db_connection.execute("SELECT * from transaction_record")
        rows = await cursor.fetchall()
        await cursor.close()
        records = []

        for row in rows:
            records.append(self._row_to_singleton_record(record))

        return records

    async def get_singleton_record(self, coin_id: bytes32) -> Optional[SingletonRecord]:
        """
        Checks DB for SingletonRecord with coin_id: coin_id and returns it.
        """
        # if tx_id in self.tx_record_cache:
        #     return self.tx_record_cache[tx_id]

        cursor = await self.db_connection.execute("SELECT * from singleton_records WHERE coin_id=?", (coin_id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return self._row_to_singleton_record(row)
        return None

    async def get_latest_singleton(self, launcher_id: bytes32) -> Optional[SingletonRecord]:
        """
        Checks DB for SingletonRecords with launcher_id: launcher_id and returns the most recent.
        """
        # if tx_id in self.tx_record_cache:
        #     return self.tx_record_cache[tx_id]

        cursor = await self.db_connection.execute(
            "SELECT * from singleton_records WHERE launcher_id=?" " ORDER BY count DESC LIMIT 1", (launcher_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return self._row_to_singleton_record(row)
        return None
