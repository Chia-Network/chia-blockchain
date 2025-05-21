from __future__ import annotations
from typing import Any

import chia_rs

from chia.types.blockchain_format.program import Program

class SerializedProgram(chia_rs.Program):
    """
    SerializedProgram is a wrapper around the chia_rs.Program class.
    It provides additional methods and properties specific to the Chia blockchain.
    """

    def to_program(self) -> Program:
        """
        Convert the SerializedProgram to a Program object.
        """
        return Program.from_bytes(self.to_bytes())
    
    @classmethod
    def from_program(cls, program: Program) -> SerializedProgram:
        """
        Convert a Program object to a SerializedProgram.
        """
        return SerializedProgram.from_bytes(bytes(program))
    
    def uncurry(self) -> tuple[Program, Program]:
        self.to_program().uncurry()

    def run_with_cost(self, max_cost: int, args: Any):
        return self.to_program().run_with_cost(max_cost, args)
    
    def run_mempool_with_cost(self, max_cost: int, args: Any):
        return self.to_program().run_with_cost(max_cost, args, chia_rs.MEMPOOL_MODE)