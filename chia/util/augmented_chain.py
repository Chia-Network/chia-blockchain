from __future__ import annotations

from typing import Dict, List, Optional

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import SubEpochChallengeSegment
from chia.util.ints import uint32


class AugmentedBlockchain(BlockchainInterface):
    _underlying: BlockchainInterface
    _extra_blocks: Dict[bytes32, BlockRecord]
    _height_to_hash: Dict[uint32, bytes32]

    def __init__(self, underlying: BlockchainInterface, extra_blocks: Dict[bytes32, BlockRecord]) -> None:
        self._underlying = underlying
        self._extra_blocks = extra_blocks
        self._height_to_hash = {block.height: hh for hh, block in extra_blocks.items()}

    def add_extra_block(self, block_record: BlockRecord) -> None:
        self._extra_blocks[block_record.header_hash] = block_record
        self._height_to_hash[block_record.height] = block_record.header_hash

    def get_peak(self) -> Optional[BlockRecord]:
        return self._underlying.get_peak()

    def get_peak_height(self) -> Optional[uint32]:
        return self._underlying.get_peak_height()

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        if self._underlying.contains_block(header_hash):
            return self._underlying.block_record(header_hash)
        return self._extra_blocks[header_hash]

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        header_hash = self._underlying.height_to_hash(height)
        if header_hash is not None:
            return self._underlying.block_record(header_hash)
        return self._extra_blocks[self._height_to_hash[height]]

    def get_ses_heights(self) -> List[uint32]:
        return self._underlying.get_ses_heights()

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self._underlying.get_ses(height)

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        header_hash = self._underlying.height_to_hash(height)
        if header_hash is not None:
            return header_hash
        if height in self._height_to_hash:
            return self._height_to_hash[height]
        return None

    def contains_block(self, header_hash: bytes32) -> bool:
        return self._underlying.contains_block(header_hash) or header_hash in self._extra_blocks

    async def contains_block_from_db(self, header_hash: bytes32) -> bool:
        return header_hash in self._extra_blocks or await self._underlying.contains_block_from_db(header_hash)

    def remove_block_record(self, header_hash: bytes32) -> None:
        if header_hash in self._extra_blocks:
            block = self._extra_blocks.pop(header_hash)
            self._height_to_hash.pop(block.height)
        else:
            self._underlying.remove_block_record(header_hash)

    def add_block_record(self, block_record: BlockRecord) -> None:
        self._underlying.add_block_record(block_record)

    def contains_height(self, height: uint32) -> bool:
        return height in self._height_to_hash or self._underlying.contains_height(height)

    async def warmup(self, fork_point: uint32) -> None:
        await self._underlying.warmup(fork_point)

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        block = await self._underlying.get_block_record_from_db(header_hash)
        if block is None:
            block = self._extra_blocks.get(header_hash)
        return block

    async def get_block_records_in_range(self, start: int, stop: int) -> Dict[bytes32, BlockRecord]:
        ret = {}
        for i in range(start, stop):
            if i not in self._height_to_hash:
                continue
            hh = self._height_to_hash[uint32(i)]
            ret[hh] = self._extra_blocks[hh]

        ret.update(await self._underlying.get_block_records_in_range(start, stop))
        return ret

    async def prev_block_hash(self, header_hashes: List[bytes32]) -> List[bytes32]:
        # not implemented
        print("AugmentedBlockchain 1")
        assert False

    async def get_header_blocks_in_range(
        self, start: int, stop: int, tx_filter: bool = True
    ) -> Dict[bytes32, HeaderBlock]:
        # not implemented
        print("AugmentedBlockchain 2")
        assert False

    async def get_header_block_by_height(
        self, height: int, header_hash: bytes32, tx_filter: bool = True
    ) -> Optional[HeaderBlock]:
        # not implemented
        print("AugmentedBlockchain 3")
        assert False

    async def get_block_records_at(self, heights: List[uint32]) -> List[BlockRecord]:
        # not implemented
        print("AugmentedBlockchain 4")
        assert False

    async def persist_sub_epoch_challenge_segments(
        self, sub_epoch_summary_hash: bytes32, segments: List[SubEpochChallengeSegment]
    ) -> None:
        print("AugmentedBlockchain 5")
        assert False

    async def get_sub_epoch_challenge_segments(
        self,
        sub_epoch_summary_hash: bytes32,
    ) -> Optional[List[SubEpochChallengeSegment]]:
        # not implemented
        print("AugmentedBlockchain 6")
        assert False

    def seen_compact_proofs(self, vdf_info: VDFInfo, height: uint32) -> bool:
        # not implemented
        print("AugmentedBlockchain 7")
        assert False
