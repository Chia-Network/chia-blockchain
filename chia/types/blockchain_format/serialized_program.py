from __future__ import annotations

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
        return SerializedProgram.from_bytes(program.to_bytes())