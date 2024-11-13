from __future__ import annotations

from dataclasses import dataclass

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

TIMELOCK_WRAPPER = load_clvm_maybe_recompile(
    "timelock.clsp", package_or_requirement="chia.wallet.puzzles.custody.restriction_puzzles.wrappers"
)
FORCE_COIN_ANNOUNCEMENT_WRAPPER = load_clvm_maybe_recompile(
    "force_assert_coin_announcement.clsp",
    package_or_requirement="chia.wallet.puzzles.custody.restriction_puzzles.wrappers",
)
FORCE_COIN_ANNOUNCEMENT_WRAPPER_HASH = FORCE_COIN_ANNOUNCEMENT_WRAPPER.get_tree_hash()


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
