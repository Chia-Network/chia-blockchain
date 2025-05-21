from __future__ import annotations

from typing import Any, Self

import chia_rs

from chia.types.blockchain_format.program import Program

SerializedProgram = chia_rs.Program


def to_program(self) -> Program:
    """
    Convert the SerializedProgram to a Program object.
    """
    return Program.from_bytes(bytes(self))


SerializedProgram.to_program = to_program


@classmethod
def from_program(cls, program: Program) -> Self:
    """
    Convert a Program object to a SerializedProgram.
    """
    return cls.from_bytes(bytes(program))


SerializedProgram.from_program = from_program

def _run(self, max_cost: int, flags: int, args: Any) -> tuple[int, Program]:
    return self.to_program()._run(max_cost, flags, args)


SerializedProgram._run = _run

def uncurry(self) -> tuple[Program, Program]:
    self.to_program().uncurry()


SerializedProgram.uncurry = uncurry


def run_with_cost(self, max_cost: int, args: Any):
    return self._run(max_cost, 0, args)


SerializedProgram.run_with_cost = run_with_cost


def run_mempool_with_cost(self, max_cost: int, args: Any):
    return self._run(max_cost, chia_rs.MEMPOOL_MODE, args)


SerializedProgram.run_mempool_with_cost = run_mempool_with_cost
