import dataclasses
from typing import List, Optional, Type, TypeVar

from aiosqlite import Row

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32
from chia.wallet.vc_drivers import VerifiedCredential

_T_VCStore = TypeVar("_T_VCStore", bound="VCStore")


@dataclasses.dataclass(frozen=True)
class VCRecord:
    vc: VerifiedCredential
    confirmed_at_height: uint32  # 0 == pending confirmation


def _row_to_vc_record(row: Row) -> VCRecord:  # type: ignore[empty-body]
    # TODO - VCWallet: Implement this
    ...


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
                    " launcher_id blob PRIMARY KEY,"
                    # VerifiedCredential.coin
                    " coin_id blob,"
                    " parent_coin_info blob,"
                    " puzzle_hash blob,"
                    " amount blob,"
                    # VerifiedCredential.singleton_lineage_proof
                    " singleton_lineage_proof blob,"
                    # VerifiedCredential.ownership_lineage_proof
                    " ownership_lineage_proof blob,"
                    # VerifiedCredential.inner_puzzle_hash
                    " inner_puzzle_hash blob,"
                    # VerifiedCredential.proof_provider
                    " proof_provider blob,"
                    # VerifiedCredential.proof_hash (0x00 == None)
                    " proof_hash blob,"
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

        async with self.db_wrapper.writer_maybe_transaction() as conn:  # noqa
            # TODO - VCWallet: Implement this (aand remove noqa above)
            pass

    async def get_vc_record(self, launcher_id: bytes32) -> Optional[VCRecord]:
        """
        Checks DB for VC with specified launcher_id and returns it.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from vc_records WHERE launcher_id=?", (launcher_id,))
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

    async def delete_vc_record(self, launcher_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM vc_records WHERE launcher_id=?", (launcher_id,))).close()

    async def get_vc_record_by_coin_id(self, coin_id: bytes32) -> Optional[VCRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from vc_records WHERE coin_id=?", (coin_id,))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return _row_to_vc_record(row)
        return None
