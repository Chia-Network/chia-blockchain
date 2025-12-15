from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs import BlockRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import MMRManagerProtocol
from chia.consensus.blockchain_mmr import BlockchainMMRManager


# implements BlockRecordsProtocol
class BlockCache:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlockRecordsProtocol

        _protocol_check: ClassVar[BlockRecordsProtocol] = cast("BlockCache", None)

    _block_records: dict[bytes32, BlockRecord]
    _height_to_hash: dict[uint32, bytes32]
    mmr_manager: MMRManagerProtocol

    def __init__(
        self,
        blocks: dict[bytes32, BlockRecord],
        mmr_manager: BlockchainMMRManager | None = None,
    ):
        self._block_records = blocks
        self._height_to_hash = {block.height: hh for hh, block in blocks.items()}
        if mmr_manager is not None:
            self.mmr_manager = mmr_manager
        else:
            self.mmr_manager = BlockchainMMRManager()

    def add_block(self, block: BlockRecord) -> None:
        hh = block.header_hash
        self._block_records[hh] = block
        self._height_to_hash[block.height] = hh
        self.mmr_manager.add_block_to_mmr(block.header_hash, block.prev_hash, block.height)

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._block_records[header_hash]

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        # Precondition: height is < peak height
        header_hash: bytes32 | None = self.height_to_hash(height)
        assert header_hash is not None
        return self.block_record(header_hash)

    def height_to_hash(self, height: uint32) -> bytes32 | None:
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

    def try_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        return self._block_records.get(header_hash)

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        return [self._block_records[h].prev_hash for h in header_hashes]
