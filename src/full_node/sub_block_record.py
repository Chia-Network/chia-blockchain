from dataclasses import dataclass

from src.util.ints import uint32, uint64, uint128
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class SubBlockRecord(Streamable):
    header_hash: bytes32
    prev_hash: bytes32
    sub_block_height: uint32
    weight: uint128
    total_iters: uint128

    @property
    def height(self):
        return self.sub_block_height
