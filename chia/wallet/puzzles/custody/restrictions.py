from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

FIXED_CREATE_COIN_DESTINATIONS = load_clvm_maybe_recompile(
    "fixed_create_coin_destinations.clsp", package_or_requirement="chia.wallet.puzzles.custody"
)
SEND_MESSAGE_BANNED = load_clvm_maybe_recompile(
    "send_message_banned.clsp", package_or_requirement="chia.wallet.puzzles.custody"
)
HEIGHTLOCK_WRAPPER = load_clvm_maybe_recompile("heightlock.clsp", package_or_requirement="chia.wallet.puzzles.custody")


@dataclass(frozen=True)
class Heightlock:
    heightlock: uint32

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return HEIGHTLOCK_WRAPPER.curry(self.heightlock)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class FixedCreateCoinDestinations:
    allowed_ph: bytes32

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return FIXED_CREATE_COIN_DESTINATIONS.curry(self.allowed_ph)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class SendMessageBanned:
    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return SEND_MESSAGE_BANNED

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()  # TODO: optimize
