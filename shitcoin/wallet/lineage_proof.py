from dataclasses import dataclass
from typing import Optional

from shitcoin.types.blockchain_format.sized_bytes import bytes32
from shitcoin.util.ints import uint64
from shitcoin.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class LineageProof(Streamable):
    parent_name: bytes32
    inner_puzzle_hash: Optional[bytes32]
    amount: uint64
