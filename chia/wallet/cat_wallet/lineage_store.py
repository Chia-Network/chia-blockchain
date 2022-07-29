import logging
from typing import Dict, Optional

import aiosqlite

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.wallet.lineage_proof import LineageProof

log = logging.getLogger(__name__)


class CATLineageStore:
    """
    WalletPuzzleStore keeps track of all generated puzzle_hashes and their derivation path / wallet.
    This is only used for HD wallets where each address is derived from a public key. Otherwise, use the
    WalletInterestedStore to keep track of puzzle hashes which we are interested in.
    """

    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper
    table_name: str

    @classmethod
    async def create(cls, db_wrapper: DBWrapper, asset_id: str, in_transaction=False):
        self = cls()
        self.table_name = f"lineage_proofs_{asset_id}"
        self.db_wrapper = db_wrapper
        self.db_connection = self.db_wrapper.db
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            await self.db_connection.execute(
                (f"CREATE TABLE IF NOT EXISTS {self.table_name}(" " coin_id text PRIMARY KEY," " lineage blob)")
            )
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()
        return self

    async def close(self):
        await self.db_connection.close()

    async def _clear_database(self):
        cursor = await self.db_connection.execute(f"DELETE FROM {self.table_name}")
        await cursor.close()
        await self.db_connection.commit()

    async def add_lineage_proof(self, coin_id: bytes32, lineage: LineageProof, in_transaction) -> None:
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute(
                f"INSERT OR REPLACE INTO {self.table_name} VALUES(?, ?)",
                (coin_id.hex(), bytes(lineage)),
            )

            await cursor.close()
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()

    async def remove_lineage_proof(self, coin_id: bytes32, in_transaction=True) -> None:
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute(
                f"DELETE FROM {self.table_name} WHERE coin_id=?;",
                (coin_id.hex(),),
            )

            await cursor.close()
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()

    async def get_lineage_proof(self, coin_id: bytes32) -> Optional[LineageProof]:

        cursor = await self.db_connection.execute(
            f"SELECT * FROM {self.table_name} WHERE coin_id=?;",
            (coin_id.hex(),),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] is not None:
            return LineageProof.from_bytes(row[1])

        return None

    async def get_all_lineage_proofs(self) -> Dict[bytes32, LineageProof]:
        cursor = await self.db_connection.execute(f"SELECT * FROM {self.table_name}")
        rows = await cursor.fetchall()
        await cursor.close()

        lineage_dict = {}

        for row in rows:
            lineage_dict[bytes32.from_hexstr(row[0])] = LineageProof.from_bytes(row[1])

        return lineage_dict
