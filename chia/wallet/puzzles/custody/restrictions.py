from __future__ import annotations

from dataclasses import dataclass

from chia_puzzles_py import programs as puzzle_mods
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64
from sortedcontainers.sorteddict import Mapping

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.custody.custody_architecture import (
    DELEGATED_PUZZLE_FEEDER_HASH,
    INDEX_WRAPPER_HASH,
    RESTRICTION_MOD_HASH,
    MemberOrDPuz,
    MofN,
    OneOfN_MOD_HASH,
    Puzzle,
    PuzzleWithRestrictions,
    Restriction,
    RestrictionHint,
    UnknownRestriction,
)
from chia.wallet.util.merkle_tree import hash_an_atom

TIMELOCK_WRAPPER = Program.from_bytes(puzzle_mods.TIMELOCK)
FORCE_1_OF_2_W_RESTRICTED_VARIABLE = Program.from_bytes(puzzle_mods.FORCE_1_OF_2_W_RESTRICTED_VARIABLE)


@dataclass(frozen=True)
class Timelock:
    timelock: uint64

    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return TIMELOCK_WRAPPER.curry(self.timelock)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class Force1of2wRestrictedVariable:
    left_side_hash: bytes32
    right_side_restrictions: list[Restriction[MemberOrDPuz]]

    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(
            [
                [restriction.member_not_dpuz, restriction.puzzle_hash(nonce), restriction.memo(nonce)]
                for restriction in self.right_side_restrictions
            ]
        )

    @classmethod
    def from_memo(cls, memo: Program, left_side_hash: bytes32) -> Force1of2wRestrictedVariable:
        restriction_hints = []
        for single_memo in memo.as_iter():
            member_not_dpuz, puzzle_hash, restriction_memo = single_memo.as_iter()
            restriction_hints.append(
                RestrictionHint(
                    member_not_dpuz is not Program.to(None), bytes32(puzzle_hash.as_atom()), restriction_memo
                )
            )
        return Force1of2wRestrictedVariable(
            left_side_hash=left_side_hash,
            right_side_restrictions=[UnknownRestriction(restriction_hint) for restriction_hint in restriction_hints],
        )

    def fill_in_unknown_puzzles(
        self, puzzle_dict: Mapping[bytes32, Restriction[MemberOrDPuz]]
    ) -> Force1of2wRestrictedVariable:
        new_restrictions: list[Restriction[MemberOrDPuz]] = []
        for restriction in self.right_side_restrictions:
            if isinstance(restriction, UnknownRestriction) and restriction.restriction_hint.puzhash in puzzle_dict:
                new_restrictions.append(puzzle_dict[restriction.restriction_hint.puzhash])
            else:
                new_restrictions.append(restriction)

        return Force1of2wRestrictedVariable(
            left_side_hash=self.left_side_hash,
            right_side_restrictions=new_restrictions,
        )

    def puzzle(self, nonce: int) -> Program:
        return FORCE_1_OF_2_W_RESTRICTED_VARIABLE.curry(
            DELEGATED_PUZZLE_FEEDER_HASH,
            OneOfN_MOD_HASH,
            hash_an_atom(self.left_side_hash),
            INDEX_WRAPPER_HASH,
            nonce,
            RESTRICTION_MOD_HASH,
            Program.to(
                [
                    restriction.puzzle(nonce)
                    for restriction in self.right_side_restrictions
                    if restriction.member_not_dpuz
                ]
            ).get_tree_hash(),
            Program.to(
                [
                    restriction.puzzle(nonce)
                    for restriction in self.right_side_restrictions
                    if not restriction.member_not_dpuz
                ]
            ).get_tree_hash(),
        )

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def anticipated_pwr(
        self, nonce: int, left_side_pwr: PuzzleWithRestrictions, right_side_member: Puzzle
    ) -> PuzzleWithRestrictions:
        anticipated_right_side_pwr = PuzzleWithRestrictions(nonce, self.right_side_restrictions, right_side_member)
        anticipated_m_of_n = MofN(m=1, members=[left_side_pwr, anticipated_right_side_pwr])
        return PuzzleWithRestrictions(nonce, [], anticipated_m_of_n)
