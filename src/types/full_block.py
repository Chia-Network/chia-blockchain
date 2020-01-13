from dataclasses import dataclass

from src.types.body import Body
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    header_block: HeaderBlock
    body: Body

    @property
    def prev_header_hash(self) -> bytes32:
        return self.header_block.header.data.prev_header_hash

    @property
    def height(self) -> uint32:
        return self.header_block.height

    @property
    def weight(self) -> uint64:
        if self.header_block.challenge:
            return self.header_block.challenge.total_weight
        else:
            return uint64(0)

    @property
    def header_hash(self) -> bytes32:
        return self.header_block.header.header_hash
