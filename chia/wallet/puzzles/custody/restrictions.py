from __future__ import annotations

from dataclasses import dataclass

from chia_puzzles_py import programs as puzzle_mods
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.program import Program

TIMELOCK_WRAPPER = Program.from_bytes(puzzle_mods.TIMELOCK)


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
