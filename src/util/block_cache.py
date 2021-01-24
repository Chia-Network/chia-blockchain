import logging
from typing import Dict, List, Optional

from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.weight_proof import BlockchainInterface
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.ints import uint32


class BlockCache(BlockchainInterface):
    def __init__(
        self,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        headers: Dict[bytes32, HeaderBlock] = {},
        sub_height_to_hash: Dict[uint32, bytes32] = {},
        sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {},
    ):
        self._sub_blocks = sub_blocks
        self._headers = headers
        self._sub_height_to_hash = sub_height_to_hash
        self._sub_epoch_summaries = sub_epoch_summaries
        self.log = logging.getLogger(__name__)

    def sub_block_record(self, header_hash: bytes32) -> SubBlockRecord:
        return self._sub_blocks[header_hash]

    def height_to_sub_block_record(self, height: uint32, check_db=False) -> SubBlockRecord:
        header_hash = self.sub_height_to_hash(height)
        return self.sub_block_record(header_hash)

    def get_ses_heights(self) -> List[uint32]:
        return sorted(self._sub_epoch_summaries.keys())

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self._sub_epoch_summaries[height]

    def get_ses_from_height(self, height: uint32) -> List[SubEpochSummary]:
        ses_l = []
        for ses_height in reversed(self.get_ses_heights()):
            if ses_height <= height:
                break
            ses_l.append(self.get_ses(ses_height))
        return ses_l

    def sub_height_to_hash(self, height: uint32) -> Optional[bytes32]:
        if height not in self._sub_height_to_hash:
            self.log.warning(f"could not find height in cache {height}")
            return None
        return self._sub_height_to_hash[height]

    def contains_sub_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._sub_blocks

    def contains_sub_height(self, sub_height: uint32) -> bool:
        return sub_height in self._sub_height_to_hash

    async def get_sub_block_records_in_range(self, start: int, stop: int) -> Dict[bytes32, SubBlockRecord]:
        return self._sub_blocks

    async def get_sub_block_from_db(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        return self._sub_blocks[header_hash]

    def remove_sub_block(self, header_hash: bytes32):
        del self._sub_blocks[header_hash]

    def add_sub_block(self, sub_block: SubBlockRecord):
        self._sub_blocks[sub_block] = sub_block

    async def get_header_blocks_in_range(self, start: int, stop: int) -> Dict[bytes32, HeaderBlock]:
        return self._headers

    async def get_header_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        return self._headers[header_hash]
