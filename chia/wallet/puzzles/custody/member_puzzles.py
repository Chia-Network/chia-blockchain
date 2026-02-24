from __future__ import annotations

from dataclasses import dataclass

from chia_puzzles_py import programs as puzzle_mods
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    calculate_synthetic_public_key,
    calculate_synthetic_secret_key,
)
from chia.wallet.singleton import SINGLETON_LAUNCHER_PUZZLE_HASH, SINGLETON_TOP_LAYER_MOD_HASH

BLS_WITH_TAPROOT_MEMBER_MOD = Program.from_bytes(puzzle_mods.BLS_WITH_TAPROOT_MEMBER)

SINGLETON_MEMBER_MOD = Program.from_bytes(puzzle_mods.SINGLETON_MEMBER)

FIXED_PUZZLE_MEMBER_MOD = Program.from_bytes(puzzle_mods.FIXED_PUZZLE_MEMBER)


@dataclass(kw_only=True, frozen=True)
class BLSWithTaprootMember:
    synthetic_key: G1Element | None = None
    public_key: G1Element | None = None
    hidden_puzzle: Program | None = None  # must be specified manually due to frozen class

    def __post_init__(self) -> None:
        if self.synthetic_key is None and (self.public_key is None or self.hidden_puzzle is None):
            raise ValueError("Must specify either the synthetic key or public key and hidden puzzle")

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        if self.synthetic_key is None:
            assert self.public_key is not None and self.hidden_puzzle is not None
            synthetic_public_key = calculate_synthetic_public_key(self.public_key, self.hidden_puzzle.get_tree_hash())
            return BLS_WITH_TAPROOT_MEMBER_MOD.curry(bytes(synthetic_public_key))
        else:
            return BLS_WITH_TAPROOT_MEMBER_MOD.curry(bytes(self.synthetic_key))

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def sign_with_synthetic_secret_key(self, original_secret_key: PrivateKey, message: bytes) -> G2Element:
        if self.hidden_puzzle is None:
            raise ValueError("Hidden puzzle must be specified to sign with synthetic secret key")
        synthetic_sk = calculate_synthetic_secret_key(original_secret_key, self.hidden_puzzle.get_tree_hash())
        return AugSchemeMPL.sign(synthetic_sk, message)

    def solve(self, use_hidden_puzzle: bool = False) -> Program:
        if use_hidden_puzzle:
            if self.hidden_puzzle is None or self.public_key is None:
                raise ValueError("Hidden puzzle or original key are unknown")
            return Program.to([self.public_key, self.hidden_puzzle])
        return Program.to([0])


@dataclass(kw_only=True, frozen=True)
class SingletonMember:
    singleton_id: bytes32
    singleton_mod_hash: bytes32 = SINGLETON_TOP_LAYER_MOD_HASH
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_PUZZLE_HASH

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        singleton_struct = (self.singleton_mod_hash, (self.singleton_id, self.singleton_launcher_hash))
        return SINGLETON_MEMBER_MOD.curry(singleton_struct)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def solve(self, singleton_inner_puzzle_hash: bytes32) -> Program:
        return Program.to([singleton_inner_puzzle_hash])


@dataclass(kw_only=True, frozen=True)
class FixedPuzzleMember:
    fixed_puzzle_hash: bytes32

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return FIXED_PUZZLE_MEMBER_MOD.curry(self.fixed_puzzle_hash)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def solve(self) -> Program:
        return Program.to([])
