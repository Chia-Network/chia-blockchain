from dataclasses import dataclass
from typing import Optional

from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class CCParent(Streamable):
    parent_name: bytes32
    inner_puzzle_hash: Optional[bytes32]
    amount: uint64
