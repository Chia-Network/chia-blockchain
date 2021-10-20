import dataclasses

from typing import Optional, List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64

@dataclasses.dataclass
class Payment:
    puzzle_hash: bytes32
    amount: uint64
    memos: Optional[List[Optional[bytes]]] = None
    extra_conditions: Optional[List[List]] = None