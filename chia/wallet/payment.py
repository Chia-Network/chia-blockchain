from __future__ import annotations

from dataclasses import dataclass, field

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


# This class is supposed to correspond to a CREATE_COIN condition
@dataclass(frozen=True)
class Payment:
    puzzle_hash: bytes32
    amount: uint64
    memos: list[bytes] = field(default_factory=list)

    def as_condition_args(self) -> list:
        return [self.puzzle_hash, self.amount, self.memos]

    def as_condition(self) -> Program:
        return Program.to([51, *self.as_condition_args()])

    def name(self) -> bytes32:
        return self.as_condition().get_tree_hash()

    @classmethod
    def from_condition(cls, condition: Program) -> Payment:
        python_condition: list = condition.as_python()
        puzzle_hash, amount = python_condition[1:3]
        memos: list[bytes] = []
        if len(python_condition) > 3:
            memos = python_condition[3]
        return cls(bytes32(puzzle_hash), uint64(int.from_bytes(amount, "big")), memos)
