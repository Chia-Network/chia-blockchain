from src.util.streamable import streamable
from src.types.block_body import BlockBody
from src.types.foliage_block import FoliageBlock


@streamable
class FullBlock:
    foliage_block: FoliageBlock
    body: BlockBody
