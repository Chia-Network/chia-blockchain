from __future__ import annotations

import dataclasses
from functools import cmp_to_key
from typing import Dict, List, Optional, Tuple, Type, TypeVar

from aiosqlite import Row

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.util.merkle_utils import list_to_binary_tree
from chia.wallet.vc_wallet.vc_drivers import VCLineageProof, VerifiedCredential


@dataclasses.dataclass(frozen=True)
class VCProofs:
    key_value_pairs: Dict[str, str]

    def as_program(self) -> Program:
        def byte_sort_pairs(f1: Tuple[str, str], f2: Tuple[str, str]) -> int:
            return 1 if Program.to([10, (1, f1[0]), (1, f2[0])]).run([]) == Program.to(None) else -1

        prog: Program = Program.to(
            list_to_binary_tree(
                list(
                    sorted(
                        self.key_value_pairs.items(),
                        key=cmp_to_key(byte_sort_pairs),
                    )
                )
            )
        )
        return prog

    def root(self) -> bytes32:
        return self.as_program().get_tree_hash()

    @staticmethod
    def from_program(prog: Program) -> VCProofs:
        first: Program = prog.at("f")
        rest: Program = prog.at("r")
        if first.atom is None and rest.atom is None:
            final_dict: Dict[str, str] = {}
            final_dict.update(VCProofs.from_program(first).key_value_pairs)
            final_dict.update(VCProofs.from_program(rest).key_value_pairs)
            return VCProofs(final_dict)
        elif first.atom is not None and rest.atom is not None:
            return VCProofs({first.atom.decode("utf-8"): rest.atom.decode("utf-8")})
        else:
            raise ValueError("Malformatted VCProofs program")  # pragma: no cover


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
                    # VerifiedCredential.proof_hash
                    " proof_hash text,"
                    # VCRecord.confirmed_height
                    " confirmed_height int)"
                )
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_id_index ON vc_records(coin_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS proof_provider_index ON vc_records(proof_provider)")

            await conn.execute("CREATE TABLE IF NOT EXISTS vc_proofs(root text PRIMARY KEY, proofs blob)")

        return self

    async def _clear_database(self) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:  # pragma: no cover
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

    # Coverage coming with CR-CAT Wallet
    async def get_vc_records_by_providers(self, provider_ids: List[bytes32]) -> List[VCRecord]:  # pragma: no cover
        """
        Checks DB for VCs with a proof_provider in a specified list and returns them.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            providers_param: str = ",".join(["?"] * len(provider_ids))
            cursor = await conn.execute(
                f"SELECT * from vc_records WHERE proof_provider IN {providers_param} LIMIT 1000", provider_ids
            )
            rows = await cursor.fetchall()
            await cursor.close()

        return [_row_to_vc_record(row) for row in rows]

    async def get_unconfirmed_vcs(self) -> List[VCRecord]:
        """
        Returns all VCs that have not yet been marked confirmed (confirmed_height == 0)
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from vc_records WHERE confirmed_height=0 LIMIT 1000")
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
            cursor = await conn.execute("SELECT * from vc_records WHERE coin_id=? LIMIT 1000", (coin_id.hex(),))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return _row_to_vc_record(row)
        return None

    async def add_vc_proofs(self, vc_proofs: VCProofs) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "INSERT INTO vc_proofs VALUES(?, ?)", (vc_proofs.root().hex(), bytes(vc_proofs.as_program()))
            )

    async def get_proofs_for_root(self, root: bytes32) -> Optional[VCProofs]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT proofs FROM vc_proofs WHERE root=?", (root.hex(),))
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None  # pragma: no cover
            else:
                return VCProofs.from_program(Program.from_bytes(row[0]))
