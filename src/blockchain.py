# from hashlib import sha256
from typing import List, Dict
from src.types.sized_bytes import bytes32
from src.types.foliage_block import FoliageBlock
from src.types.block_body import BlockBody
from src.types.block_header import BlockHeader


class Blockchain:
    heads: List[FoliageBlock] = []
    blocks: Dict[bytes32, FoliageBlock] = {}

    # def __init__(self, genesis_block_foliage: FoliageBlock):
    #     self.heads = [genesis_block_foliage]
    #     self.blocks[sha256(genesis_block_foliage.header).digest()] = genesis_block_foliage

    def get_current_heads(self) -> FoliageBlock:
        return self.heads

    def add_block(self, new_block_foliage, new_block_body: BlockBody) -> bool:
        if new_block_foliage.challenge.height > min([b.challenge.height for b in self.heads]):
            self.heads.append(new_block_foliage)
            self.heads = sorted(self.heads, key=lambda b: b.challenge.height)[1:4]
            return True

        return False

    def block_can_be_added(self, new_block_header: BlockHeader, new_block_body: BlockBody):
        # new_block_header.data.previous_header_hash
        # hashes: List[bytes32] = [sha256(h.header.data).digest() for h in self.heads]
        # if new_block_header.data.previous_header_hash not in hashes:
        #     return False

        # TODO: validate everything
        return True
