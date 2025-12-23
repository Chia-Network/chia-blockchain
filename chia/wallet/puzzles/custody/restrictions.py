from __future__ import annotations

from dataclasses import dataclass

from chia_puzzles_py import programs as puzzle_mods
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

TIMELOCK_WRAPPER = Program.from_bytes(puzzle_mods.TIMELOCK)
FIXED_CREATE_COIN_DESTINATIONS = load_clvm_maybe_recompile(
    "fixed_create_coin_destinations.clsp", package_or_requirement="chia.wallet.puzzles.custody"
)
SEND_MESSAGE_BANNED = load_clvm_maybe_recompile(
    "send_message_banned.clsp", package_or_requirement="chia.wallet.puzzles.custody"
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


@dataclass(kw_only=True, frozen=True)
class FixedCreateCoinDestinations:
    allowed_ph: bytes32

    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return FIXED_CREATE_COIN_DESTINATIONS.curry(self.allowed_ph)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class SendMessageBanned:
    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return SEND_MESSAGE_BANNED

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()  # TODO: optimize
