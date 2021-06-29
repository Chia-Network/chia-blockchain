from dataclasses import dataclass
from typing import Optional

from deafwave.types.blockchain_format.sized_bytes import bytes32
from deafwave.util.ints import uint64
from deafwave.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CCParent(Streamable):
    parent_name: bytes32
    inner_puzzle_hash: Optional[bytes32]
    amount: uint64
