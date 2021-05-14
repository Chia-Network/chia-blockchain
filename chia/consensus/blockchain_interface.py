from typing import Dict, List, Optional

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import SubEpochChallengeSegment
from chia.util.ints import uint32


class BlockchainInterface:
    def get_peak_height(self) -> Optional[uint32]:
        pass

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        pass

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        pass

    def get_ses_heights(self) -> List[uint32]:
        pass

    def get_ses(self, height: uint32) -> SubEpochSummary:
        pass

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        pass

    def contains_block(self, header_hash: bytes32) -> bool:
        pass

    def remove_block_record(self, header_hash: bytes32):
        pass

    def add_block_record(self, block_record: BlockRecord):
        pass

    def contains_height(self, height: uint32) -> bool:
        pass

    async def warmup(self, fork_point: uint32):
        pass

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        pass

    async def get_block_records_in_range(self, start: int, stop: int) -> Dict[bytes32, BlockRecord]:
        pass

    async def get_header_blocks_in_range(
        self, start: int, stop: int, tx_filter: bool = True
    ) -> Dict[bytes32, HeaderBlock]:
        pass

    async def get_header_block_by_height(
        self, height: int, header_hash: bytes32, tx_filter: bool = True
    ) -> Optional[HeaderBlock]:
        pass

    async def get_block_records_at(self, heights: List[uint32]) -> List[BlockRecord]:
        pass

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if self.contains_block(header_hash):
            return self.block_record(header_hash)
        return None

    async def persist_sub_epoch_challenge_segments(
        self, sub_epoch_summary_height: uint32, segments: List[SubEpochChallengeSegment]
    ):
        pass

    async def get_sub_epoch_challenge_segments(
        self,
        sub_epoch_summary_height: uint32,
    ) -> Optional[List[SubEpochChallengeSegment]]:
        pass

    def seen_compact_proofs(self, vdf_info: VDFInfo, height: uint32) -> bool:
        pass
