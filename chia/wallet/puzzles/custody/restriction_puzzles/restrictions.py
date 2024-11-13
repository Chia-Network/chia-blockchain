from __future__ import annotations

from dataclasses import dataclass

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
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
)
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.util.merkle_tree import hash_an_atom

TIMELOCK_WRAPPER = load_clvm_maybe_recompile(
    "timelock.clsp", package_or_requirement="chia.wallet.puzzles.custody.restriction_puzzles.wrappers"
)
FORCE_COIN_ANNOUNCEMENT_WRAPPER = load_clvm_maybe_recompile(
    "force_assert_coin_announcement.clsp",
    package_or_requirement="chia.wallet.puzzles.custody.restriction_puzzles.wrappers",
)
FORCE_COIN_ANNOUNCEMENT_WRAPPER_HASH = FORCE_COIN_ANNOUNCEMENT_WRAPPER.get_tree_hash()
FORCE_1_OF_2_W_RESTRICTED_VARIABLE = load_clvm_maybe_recompile(
    "force_1_of_2_w_restricted_variable.clsp",
    package_or_requirement="chia.wallet.puzzles.custody.restriction_puzzles.wrappers",
)


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
class ForceCoinAnnouncement:
    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return FORCE_COIN_ANNOUNCEMENT_WRAPPER

    def puzzle_hash(self, nonce: int) -> bytes32:
        return FORCE_COIN_ANNOUNCEMENT_WRAPPER_HASH


@dataclass(frozen=True)
class Force1of2wRestrictedVariable:
    left_side_hash: bytes32
    right_side_restrictions: list[Restriction[MemberOrDPuz]]

    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

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
