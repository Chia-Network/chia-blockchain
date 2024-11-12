from __future__ import annotations

from dataclasses import dataclass

from chia_rs import G1Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.custody.custody_architecture import Puzzle
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.singleton import SINGLETON_LAUNCHER_PUZZLE_HASH, SINGLETON_TOP_LAYER_MOD_HASH

BLS_MEMBER_MOD = load_clvm_maybe_recompile(
    "bls_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SINGLETON_MEMBER_MOD = load_clvm_maybe_recompile(
    "singleton_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)


@dataclass(frozen=True)
class BLSMember(Puzzle):
    public_key: G1Element

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return BLS_MEMBER_MOD.curry(bytes(self.public_key))

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class SingletonMember(Puzzle):
    singleton_id: bytes32

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        singleton_struct = (SINGLETON_TOP_LAYER_MOD_HASH, (self.singleton_id, SINGLETON_LAUNCHER_PUZZLE_HASH))
        return SINGLETON_MEMBER_MOD.curry(singleton_struct)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()
