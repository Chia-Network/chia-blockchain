from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Dict, List, Optional, cast

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32


# implements BlockRecordsProtocol
class BlockCache:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlockRecordsProtocol

        _protocol_check: ClassVar[BlockRecordsProtocol] = cast("BlockCache", None)

    _block_records: Dict[bytes32, BlockRecord]
    _height_to_hash: Dict[uint32, bytes32]
    _peak_height: Optional[uint32]

    def __init__(
        self,
        blocks: Dict[bytes32, BlockRecord],
    ):
        self._block_records = blocks
        self._height_to_hash = {}
        self._peak_height = uint32(0)
        for hh, block in blocks.items():
            self._height_to_hash[block.height] = hh
            if self._peak_height is None or block.height > self._peak_height:
                self._peak_height = block.height

    def add_block(self, block: BlockRecord) -> None:
        hh = block.header_hash
        self._block_records[hh] = block
        self._height_to_hash[block.height] = hh
        if self._peak_height is None or block.height > self._peak_height:
            self._peak_height = block.height

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

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._block_records

    def get_peak_height(self) -> Optional[uint32]:
        return self._peak_height

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        return self._block_records.get(header_hash)

    async def prev_block_hash(self, header_hashes: List[bytes32]) -> List[bytes32]:
        return [self._block_records[h].prev_hash for h in header_hashes]
