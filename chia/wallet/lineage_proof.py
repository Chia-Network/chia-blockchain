from dataclasses import dataclass
from typing import Optional

from tad.types.blockchain_format.sized_bytes import bytes32
from tad.util.ints import uint64
from tad.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class LineageProof(Streamable):
    parent_name: bytes32
    inner_puzzle_hash: Optional[bytes32]
    amount: uint64
