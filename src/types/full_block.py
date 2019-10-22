from src.util.ints import uint32, uint64
from src.types.sized_bytes import bytes32
from src.util.streamable import streamable, Streamable
from src.types.block_body import BlockBody
from src.types.trunk_block import TrunkBlock
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    trunk_block: TrunkBlock
    body: BlockBody

    @property
    def prev_header_hash(self) -> bytes32:
        return self.trunk_block.header.data.prev_header_hash

    @property
    def height(self) -> uint32:
        return self.body.coinbase.height

    @property
    def weight(self) -> uint64:
        if (self.trunk_block.challenge):
            return self.trunk_block.challenge.total_weight
        else:
            return uint64(0)

    @property
    def header_hash(self) -> bytes32:
        return self.trunk_block.header.header_hash
