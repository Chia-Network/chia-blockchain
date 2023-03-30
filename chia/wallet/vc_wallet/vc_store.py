from __future__ import annotations

import dataclasses
from typing import List, Optional, Type, TypeVar

from aiosqlite import Row
from chia_rs.chia_rs import Coin

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.vc_wallet.vc_drivers import VCLineageProof, VerifiedCredential

_T_VCStore = TypeVar("_T_VCStore", bound="VCStore")


@streamable
@dataclasses.dataclass(frozen=True)
class VCRecord(Streamable):
    vc: VerifiedCredential
    confirmed_at_height: uint32  # 0 == pending confirmation


def _row_to_vc_record(row: Row) -> VCRecord:
    return VCRecord(
        VerifiedCredential(
            Coin(bytes32.from_hexstr(row[2]), bytes32.from_hexstr(row[3]), uint64.from_bytes(row[4])),
            LineageProof.from_bytes(row[5]),
            VCLineageProof.from_bytes(row[6]),
            bytes32.from_hexstr(row[0]),
            bytes32.from_hexstr(row[7]),
            bytes32.from_hexstr(row[8]),
            None if row[9] is None else bytes32.from_hexstr(row[9]),
        ),
        uint32(row[10]),
    )


class VCStore:
    """
    WalletUserStore keeps track of all user created wallets and necessary smart-contract data
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls: Type[_T_VCStore], db_wrapper: DBWrapper2) -> _T_VCStore:
        self = cls()

        self.db_wrapper = db_wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS vc_records("
                    # VerifiedCredential.launcher_id
                    " launcher_id text PRIMARY KEY,"
                    # VerifiedCredential.coin
                    " coin_id text,"
                    " parent_coin_info text,"
                    " puzzle_hash text,"
                    " amount blob,"
                    # VerifiedCredential.singleton_lineage_proof
                    " singleton_lineage_proof blob,"
                    # VerifiedCredential.ownership_lineage_proof
                    " ownership_lineage_proof blob,"
                    # VerifiedCredential.inner_puzzle_hash
                    " inner_puzzle_hash text,"
                    # VerifiedCredential.proof_provider
                    " proof_provider text,"
                    # VerifiedCredential.proof_hash (0x00 == None)
                    " proof_hash text,"
                    # VCRecord.confirmed_height
                    " confirmed_height int)"
                )
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_id_index ON vc_records(coin_id)")

        return self

    async def _clear_database(self) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM vc_records")).close()

    async def add_or_replace_vc_record(self, record: VCRecord) -> None:
        """
        Store VCRecord in DB.

        If a record with the same launcher ID exists, it will only be replaced if the new record has a higher
        confirmation height.
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "INSERT or REPLACE INTO vc_records VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.vc.launcher_id.hex(),
                    record.vc.coin.name().hex(),
                    record.vc.coin.parent_coin_info.hex(),
                    record.vc.coin.puzzle_hash.hex(),
                    bytes(uint64(record.vc.coin.amount)),
                    bytes(record.vc.singleton_lineage_proof),
                    bytes(record.vc.eml_lineage_proof),
                    record.vc.inner_puzzle_hash.hex(),
                    record.vc.proof_provider.hex(),
                    None if record.vc.proof_hash is None else record.vc.proof_hash.hex(),
                    record.confirmed_at_height,
                ),
            )

    async def get_vc_record(self, launcher_id: bytes32) -> Optional[VCRecord]:
        """
        Checks DB for VC with specified launcher_id and returns it.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from vc_records WHERE launcher_id=?", (launcher_id.hex(),))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return _row_to_vc_record(row)
        return None

    async def get_unconfirmed_vcs(self) -> List[VCRecord]:
        """
        Returns all VCs that have not yet been marked confirmed (confirmed_height == 0)
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from vc_records WHERE confirmed_height=0")
            rows = await cursor.fetchall()
            await cursor.close()
        records = [_row_to_vc_record(row) for row in rows]

        return records

    async def get_vc_record_list(
        self,
        start_index: int = 0,
        count: int = 50,
    ) -> List[VCRecord]:
        """
        Return all VCs
        :param start_index: Start index
        :param count: How many records will be returned
        :return:
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(await conn.execute_fetchall("SELECT * from vc_records LIMIT ? OFFSET ? ", (count, start_index)))
        return [_row_to_vc_record(row) for row in rows]

    async def delete_vc_record(self, launcher_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM vc_records WHERE launcher_id=?", (launcher_id.hex(),))).close()

    async def get_vc_record_by_coin_id(self, coin_id: bytes32) -> Optional[VCRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from vc_records WHERE coin_id=?", (coin_id.hex(),))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return _row_to_vc_record(row)
        return None
