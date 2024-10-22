from __future__ import annotations

from dataclasses import dataclass

from chia_rs import G1Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

BLS_MEMBER_MOD = load_clvm_maybe_recompile(
    "bls_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)


@dataclass(frozen=True)
class BLSMember:
    public_key: G1Element

    def puzzle(self, nonce) -> Program:
        return BLS_MEMBER_MOD.curry(bytes(self.public_key))

    def puzzle_hash(self, nonce) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()
