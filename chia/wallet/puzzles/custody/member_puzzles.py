from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from chia_puzzles_py import programs as puzzle_mods
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.custody.custody_architecture import MIPSComponentBase
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    calculate_synthetic_public_key,
    calculate_synthetic_secret_key,
)
from chia.wallet.puzzles.puzzle_drivers import Puzzle, UnknownPuzzle, UnknownSolution
from chia.wallet.singleton import SINGLETON_LAUNCHER_PUZZLE_HASH, SINGLETON_TOP_LAYER_MOD_HASH

BLS_WITH_TAPROOT_MEMBER_MOD = Program.from_bytes(puzzle_mods.BLS_WITH_TAPROOT_MEMBER)

SINGLETON_MEMBER_MOD = Program.from_bytes(puzzle_mods.SINGLETON_MEMBER)

FIXED_PUZZLE_MEMBER_MOD = Program.from_bytes(puzzle_mods.FIXED_PUZZLE_MEMBER)

_T_Puzzle = TypeVar("_T_Puzzle", bound=Puzzle | None, default=None)


@dataclass(kw_only=True, frozen=True)
class BLSWithTaprootMember(MIPSComponentBase, Generic[_T_Puzzle]):
    synthetic_key: G1Element | None = None
    public_key: G1Element | None = None
    # must be specified manually due to frozen class
    hidden_puzzle: _T_Puzzle = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.synthetic_key is None and (self.public_key is None or self.hidden_puzzle is None):
            raise ValueError("Must specify either the synthetic key or public key and hidden puzzle")

    @property
    def memo(self) -> Program:
        return Program.to(0)

    @property
    def guaranteed_synthetic_key(self) -> G1Element:
        if self.synthetic_key is not None:
            return self.synthetic_key
        else:
            assert self.hidden_puzzle is not None  # guarded by __post_init__
            return calculate_synthetic_public_key(self.public_key, self.hidden_puzzle.tree_hash)

    @property
    def program(self) -> Program:
        return BLS_WITH_TAPROOT_MEMBER_MOD.curry(bytes(self.guaranteed_synthetic_key))

    def sign_with_synthetic_secret_key(self, original_secret_key: PrivateKey, message: bytes) -> G2Element:
        if self.hidden_puzzle is None:
            raise ValueError("Hidden puzzle must be specified to sign with synthetic secret key")
        synthetic_sk = calculate_synthetic_secret_key(original_secret_key, self.hidden_puzzle.tree_hash)
        return AugSchemeMPL.sign(synthetic_sk, message)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> BLSWithTaprootMember[None] | None:
        if unknown_puzzle.mod != BLS_WITH_TAPROOT_MEMBER_MOD or unknown_puzzle.curried_args is None:
            return None
        (synthetic_key_prog,) = unknown_puzzle.curried_args
        synthetic_key = G1Element.from_bytes(synthetic_key_prog.as_atom())
        original_key = None
        # hidden_puzzle = None
        # TODO: We need to figure out a way to implement arbitrary context as part of the matching protocol
        # if solution is not None:
        #     solution_match = BLSWithTaprootMemberSolution.match(unknown_solution=solution)
        #     if solution_match is not None:
        #         original_key = solution_match.original_public_key
        #         hidden_puzzle = solution_match.hidden_puzzle
        return BLSWithTaprootMember(synthetic_key=synthetic_key, public_key=original_key)


@dataclass(kw_only=True, frozen=True)
class BLSWithTaprootMemberSolution:
    original_public_key: G1Element | None = None
    hidden_puzzle: Puzzle | None = None

    def __post_init__(self) -> None:
        if (self.original_public_key is not None and self.hidden_puzzle is None) or (
            self.original_public_key is None and self.hidden_puzzle is not None
        ):
            raise ValueError("Must specify both or neither of original_public_key and hidden_puzzle")

    @property
    def program(self) -> Program:
        if self.hidden_puzzle is not None:
            if self.original_public_key is None:
                raise ValueError("Need original_public_key for hidden_puzzle spend")
            return Program.to([self.original_public_key, self.hidden_puzzle.program])
        return Program.to([0])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> BLSWithTaprootMemberSolution | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) == 2:
            return BLSWithTaprootMemberSolution(
                original_public_key=G1Element.from_bytes(list_of_values[0].as_atom()),
                hidden_puzzle=UnknownPuzzle(known_program=list_of_values[1]),
            )
        elif len(list_of_values) == 1:
            return BLSWithTaprootMemberSolution()
        else:
            return None


@dataclass(kw_only=True, frozen=True)
class SingletonMember(MIPSComponentBase):
    singleton_id: bytes32
    singleton_mod_hash: bytes32 = SINGLETON_TOP_LAYER_MOD_HASH
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_PUZZLE_HASH

    @property
    def memo(self) -> Program:
        return Program.to(0)

    @property
    def program(self) -> Program:
        singleton_struct = (self.singleton_mod_hash, (self.singleton_id, self.singleton_launcher_hash))
        return SINGLETON_MEMBER_MOD.curry(singleton_struct)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> SingletonMember | None: ...


@dataclass(kw_only=True, frozen=True)
class SingletonMemberSolution:
    singleton_inner_puzzle_hash: bytes32

    @property
    def program(self) -> Program:
        return Program.to([self.singleton_inner_puzzle_hash])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> SingletonMemberSolution | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 1:
            return None
        try:
            return SingletonMemberSolution(singleton_inner_puzzle_hash=bytes32(list_of_values[0].as_atom()))
        except ValueError:
            return None


@dataclass(kw_only=True, frozen=True)
class FixedPuzzleMember(MIPSComponentBase):
    fixed_puzzle_hash: bytes32

    @property
    def memo(self) -> Program:
        return Program.to(0)

    @property
    def program(self) -> Program:
        return FIXED_PUZZLE_MEMBER_MOD.curry(self.fixed_puzzle_hash)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> FixedPuzzleMember | None: ...
