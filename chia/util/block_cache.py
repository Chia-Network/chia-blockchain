from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.block_record import BlockRecord


# implements BlockRecordsProtocol
class BlockCache:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlockRecordsProtocol

        _protocol_check: ClassVar[BlockRecordsProtocol] = cast("BlockCache", None)

    _block_records: dict[bytes32, BlockRecord]
    _height_to_hash: dict[uint32, bytes32]

    def __init__(
        self,
        blocks: dict[bytes32, BlockRecord],
    ):
        self._block_records = blocks
        self._height_to_hash = {block.height: hh for hh, block in blocks.items()}

    def add_block(self, block: BlockRecord) -> None:
        hh = block.header_hash
        self._block_records[hh] = block
        self._height_to_hash[block.height] = hh

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._block_records[header_hash]

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        # Precondition: height is < peak height
        header_hash: Optional[bytes32] = self.height_to_hash(height)
        assert header_hash is not None
        return self.block_record(header_hash)

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        if height not in self._height_to_hash:
            return None
        return self._height_to_hash[height]

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        block_hash_from_hh = self.height_to_hash(height)
        if block_hash_from_hh is None or block_hash_from_hh != header_hash:
            return False
        return True

    def contains_height(self, height: uint32) -> bool:
        return height in self._height_to_hash

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        return self._block_records.get(header_hash)

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        return [self._block_records[h].prev_hash for h in header_hashes]
