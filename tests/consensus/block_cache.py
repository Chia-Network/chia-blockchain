import logging
from typing import Dict, List, Optional


from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.weight_proof import BlockchainInterface
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.ints import uint32


class BlockCache(BlockchainInterface):
    BATCH_SIZE = 300

    def __init__(
        self,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        sub_height_to_hash: Dict[uint32, bytes32] = {},
        sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {},
    ):
        self._sub_blocks = sub_blocks
        self._sub_height_to_hash = sub_height_to_hash
        self._sub_epoch_summaries = sub_epoch_summaries
        self.log = logging.getLogger(__name__)

    def sub_block_record(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        if header_hash not in self._sub_blocks:
            self.log.warning("could not find header hash in cache")
            return None

        return self._sub_blocks[header_hash]

    def height_to_sub_block_record(self, height: uint32) -> Optional[SubBlockRecord]:
        header_hash = self.sub_height_to_hash(height)
        if header_hash is None:
            return None
        return self.sub_block_record(header_hash)

    def get_ses_heights(self) -> List[bytes32]:
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
            self.log.warning("could not find height in cache")
            return None
        return self._sub_height_to_hash[height]

    def contains_sub_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._sub_blocks
