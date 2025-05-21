from __future__ import annotations

from typing import Any, Self

import chia_rs

from chia.types.blockchain_format.program import Program

SerializedProgram = chia_rs.Program


def _run(self, max_cost: int, flags: int, args: Any) -> tuple[int, Program]:
    return self.to_program().run(max_cost, flags, args)


SerializedProgram._run = _run


def to_program(self) -> Program:
    """
    Convert the SerializedProgram to a Program object.
    """
    return Program.from_bytes(self.to_bytes())


SerializedProgram.to_program = to_program


@classmethod
def from_program(cls, program: Program) -> Self:
    """
    Convert a Program object to a SerializedProgram.
    """
    return cls.from_bytes(bytes(program))


SerializedProgram.from_program = from_program


def uncurry(self) -> tuple[Program, Program]:
    self.to_program().uncurry()


SerializedProgram.uncurry = uncurry


def run_with_cost(self, max_cost: int, args: Any):
    return self.to_program().run_with_cost(max_cost, args)


SerializedProgram.run_with_cost = run_with_cost


def run_mempool_with_cost(self, max_cost: int, args: Any):
    return self.to_program().run_with_cost(max_cost, args, chia_rs.MEMPOOL_MODE)


SerializedProgram.run_mempool_with_cost = run_mempool_with_cost
