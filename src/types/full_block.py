from src.util.streamable import streamable
from src.types.block_body import BlockBody
from src.types.trunk_block import TrunkBlock


@streamable
class FullBlock:
    trunk_block: TrunkBlock
    body: BlockBody

    def is_valid(self):
        return True
