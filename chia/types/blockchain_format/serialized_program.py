# mypy: ignore-errors
# mypy does not like method assignment

from __future__ import annotations

from typing import Any

import chia_rs

from chia.types.blockchain_format.program import Program

SerializedProgram = chia_rs.Program


def _run(self, max_cost: int, flags: int, args: Any) -> tuple[int, Program]:
    result = self.run_rust(max_cost, flags, args)
    ret = (result[0], Program(result[1]))
    return ret


SerializedProgram._run = _run


def to_program(self) -> Program:
    """
    Convert the SerializedProgram to a Program object.
    """
    return Program.from_bytes(bytes(self))


SerializedProgram.to_program = to_program


@classmethod
def from_program(cls, program: Program):
    """
    Convert a Program object to a SerializedProgram.
    """
    return cls.from_bytes(bytes(program))


SerializedProgram.from_program = from_program


def uncurry(self) -> tuple[Program, Program]:
    result = self.uncurry_rust()
    return (Program(result[0]), Program(result[1]))


SerializedProgram.uncurry = uncurry


def run_with_cost(self, max_cost: int, args: Any):
    return self._run(max_cost, 0, args)


SerializedProgram.run_with_cost = run_with_cost


def run_mempool_with_cost(self, max_cost: int, args: Any):
    return self._run(max_cost, chia_rs.MEMPOOL_MODE, args)


SerializedProgram.run_mempool_with_cost = run_mempool_with_cost
