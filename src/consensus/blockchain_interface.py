from typing import List, Optional, Dict

from src.consensus.sub_block_record import SubBlockRecord
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.weight_proof import SubEpochChallengeSegment
from src.util.ints import uint32


class BlockchainInterface:
    def get_peak_height(self) -> Optional[uint32]:
        pass

    def sub_block_record(self, header_hash: bytes32) -> SubBlockRecord:
        pass

    def height_to_sub_block_record(self, height: uint32) -> SubBlockRecord:
        pass

    def get_ses_heights(self) -> List[uint32]:
        pass

    def get_ses(self, height: uint32) -> SubEpochSummary:
        pass

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        pass

    def contains_sub_block(self, header_hash: bytes32) -> bool:
        pass

    def remove_sub_block(self, header_hash: bytes32):
        pass

    def add_sub_block(self, sub_block: SubBlockRecord):
        pass

    def contains_height(self, height: uint32) -> bool:
        pass

    async def warmup(self, fork_point: uint32):
        pass

    async def get_sub_block_from_db(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        pass

    async def get_sub_block_records_in_range(self, start: int, stop: int) -> Dict[bytes32, SubBlockRecord]:
        pass

    async def get_header_blocks_in_range(self, start: int, stop: int) -> Dict[bytes32, HeaderBlock]:
        pass

    def try_sub_block(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        if self.contains_sub_block(header_hash):
            return self.sub_block_record(header_hash)
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
