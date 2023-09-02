from __future__ import annotations

import logging
from typing import Dict, Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.wallet.lineage_proof import LineageProof

log = logging.getLogger(__name__)


class CATLineageStore:
    """
    WalletPuzzleStore keeps track of all generated puzzle_hashes and their derivation path / wallet.
    This is only used for HD wallets where each address is derived from a public key. Otherwise, use the
    WalletInterestedStore to keep track of puzzle hashes which we are interested in.
    """

    db_wrapper: DBWrapper2
    table_name: str

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2, asset_id: str) -> "CATLineageStore":
        self = cls()
        self.table_name = f"lineage_proofs_{asset_id}"
        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (f"CREATE TABLE IF NOT EXISTS {self.table_name}(coin_id text PRIMARY KEY, lineage blob)")
            )
        return self

    async def add_lineage_proof(self, coin_id: bytes32, lineage: LineageProof) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                f"INSERT OR REPLACE INTO {self.table_name} VALUES(?, ?)",
                (coin_id.hex(), bytes(lineage)),
            )
            await cursor.close()

    async def remove_lineage_proof(self, coin_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                f"DELETE FROM {self.table_name} WHERE coin_id=?;",
                (coin_id.hex(),),
            )
            await cursor.close()

    async def get_lineage_proof(self, coin_id: bytes32) -> Optional[LineageProof]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                f"SELECT * FROM {self.table_name} WHERE coin_id=?;",
                (coin_id.hex(),),
            )
            row = await cursor.fetchone()
            await cursor.close()

        if row is not None and row[0] is not None:
            ret: LineageProof = LineageProof.from_bytes(row[1])
            return ret

        return None

    async def get_all_lineage_proofs(self) -> Dict[bytes32, LineageProof]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(f"SELECT * FROM {self.table_name}")
            rows = await cursor.fetchall()
            await cursor.close()

        lineage_dict = {}

        for row in rows:
            lineage_dict[bytes32.from_hexstr(row[0])] = LineageProof.from_bytes(row[1])

        return lineage_dict
