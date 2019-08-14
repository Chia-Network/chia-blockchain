from src.util.streamable import streamable
from src.types.block_body import BlockBody
from src.types.trunk_block import TrunkBlock


@streamable
class FullBlock:
    trunk_block: TrunkBlock
    body: BlockBody

    def is_valid(self):
        # TODO(alex): review, recursively. A lot of things are not verified.
        body_hash = self.body.get_hash()
        return (self.trunk_block.header.data.body_hash == body_hash
                and self.trunk_block.is_valid()
                and self.body.is_valid())
