from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.custody.custody_architecture import MIPSComponentBase
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.puzzle_drivers import UnknownPuzzle

FIXED_CREATE_COIN_DESTINATIONS = load_clvm_maybe_recompile(
    "fixed_create_coin_destinations.clsp", package_or_requirement="chia.wallet.puzzles.custody"
)
SEND_MESSAGE_BANNED = load_clvm_maybe_recompile(
    "send_message_banned.clsp", package_or_requirement="chia.wallet.puzzles.custody"
)
HEIGHTLOCK_WRAPPER = load_clvm_maybe_recompile("heightlock.clsp", package_or_requirement="chia.wallet.puzzles.custody")


@dataclass(kw_only=True, frozen=True)
class Heightlock(MIPSComponentBase):
    heightlock: uint32

    @property
    def memo(self) -> Program:
        return Program.to(None)

    @property
    def program(self) -> Program:
        return HEIGHTLOCK_WRAPPER.curry(self.heightlock)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Heightlock | None: ...


@dataclass(kw_only=True, frozen=True)
class FixedCreateCoinDestinations(MIPSComponentBase):
    allowed_ph: bytes32

    @property
    def memo(self) -> Program:
        return Program.to(None)

    @property
    def program(self) -> Program:
        return FIXED_CREATE_COIN_DESTINATIONS.curry(self.allowed_ph)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> FixedCreateCoinDestinations | None: ...


@dataclass(kw_only=True, frozen=True)
class SendMessageBanned(MIPSComponentBase):
    @property
    def memo(self) -> Program:
        return Program.to(None)

    @property
    def program(self) -> Program:
        return SEND_MESSAGE_BANNED

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> SendMessageBanned | None: ...
