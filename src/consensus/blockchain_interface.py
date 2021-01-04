from typing import List, Optional

from src.consensus.sub_block_record import SubBlockRecord
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.ints import uint32


class BlockchainInterface:
    def get_peak_height(self) -> Optional[uint32]:
        pass

    def sub_block_record(self, header_hash: bytes32) -> SubBlockRecord:
        pass

    def height_to_sub_block_record(self, height: uint32) -> SubBlockRecord:
        pass

    def get_ses_heights(self) -> List[bytes32]:
        pass

    def get_ses(self, height: uint32) -> SubEpochSummary:
        pass

    def get_ses_from_height(self, height: uint32) -> List[SubEpochSummary]:
        pass

    def sub_height_to_hash(self, height: uint32) -> Optional[bytes32]:
        pass

    def contains_sub_block(self, header_hash: bytes32) -> bool:
        pass

    def contains_sub_height(self, height: uint32) -> bool:
        pass

    def try_sub_block(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        if self.contains_sub_block(header_hash):
            return self.sub_block_record(header_hash)
        return None
