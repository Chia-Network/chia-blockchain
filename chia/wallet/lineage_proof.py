from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


class LineageProofField(Enum):
    PARENT_NAME = 1
    INNER_PUZZLE_HASH = 2
    AMOUNT = 3


@streamable
@dataclass(frozen=True)
class LineageProof(Streamable):
    parent_name: Optional[bytes32] = None
    inner_puzzle_hash: Optional[bytes32] = None
    amount: Optional[uint64] = None

    @classmethod
    def from_program(cls, program: Program, fields: List[LineageProofField]) -> LineageProof:
        lineage_proof_info: Dict[str, Any] = {}
        field_iter = iter(fields)
        program_iter = program.as_iter()
        for program_value in program_iter:
            field = next(field_iter)
            if field == LineageProofField.PARENT_NAME:
                lineage_proof_info["parent_name"] = bytes32(program_value.as_atom())
            elif field == LineageProofField.INNER_PUZZLE_HASH:
                lineage_proof_info["inner_puzzle_hash"] = bytes32(program_value.as_atom())
            elif field == LineageProofField.AMOUNT:
                lineage_proof_info["amount"] = uint64(program_value.as_int())
        try:
            next(field_iter)
            raise ValueError("Mismatch between program data and fields information")
        except StopIteration:
            pass

        return LineageProof(**lineage_proof_info)

    def to_program(self) -> Program:
        final_list: List[Any] = []
        if self.parent_name is not None:
            final_list.append(self.parent_name)
        if self.inner_puzzle_hash is not None:
            final_list.append(self.inner_puzzle_hash)
        if self.amount is not None:
            final_list.append(self.amount)
        return Program.to(final_list)

    def is_none(self) -> bool:
        return all([self.parent_name is None, self.inner_puzzle_hash is None, self.amount is None])
