from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.types.blockchain_format.serialized_program import SerializedProgram


@dataclass(frozen=True)
class GeneratorBlockInfo:
    prev_header_hash: bytes32
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: list[uint32]
