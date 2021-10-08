import aiosqlite
import logging
from typing import Dict, List, Optional
from chia.util.ints import uint32
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary

log = logging.getLogger(__name__)


class BlockHeightMap:
    db: aiosqlite.Connection

    # Defines the path from genesis to the peak, no orphan blocks
    __height_to_hash: Dict[uint32, bytes32]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the blocks in the path to the peak
    __sub_epoch_summaries: Dict[uint32, SubEpochSummary]

    @classmethod
    async def create(cls, db: aiosqlite.Connection) -> "BlockHeightMap":
        self = BlockHeightMap()
        self.db = db

        self.__height_to_hash = {}
        self.__sub_epoch_summaries = {}

        res = await self.db.execute("SELECT * from block_records WHERE is_peak = 1")
        row = await res.fetchone()
        await res.close()

        if row is None:
            return self

        # TODO: it's unsustainable to dump all block records to RAM
        # this takes a very long time where the DB is on a spinning disk
        peak: bytes32 = bytes.fromhex(row[0])
        cursor = await self.db.execute("SELECT header_hash,prev_hash,height,sub_epoch_summary from block_records")
        rows = await cursor.fetchall()
        await cursor.close()
        hash_to_prev_hash: Dict[bytes32, bytes32] = {}
        hash_to_height: Dict[bytes32, uint32] = {}
        hash_to_summary: Dict[bytes32, SubEpochSummary] = {}

        for row in rows:
            hash_to_prev_hash[bytes.fromhex(row[0])] = bytes.fromhex(row[1])
            hash_to_height[bytes.fromhex(row[0])] = row[2]
            if row[3] is not None:
                hash_to_summary[bytes.fromhex(row[0])] = SubEpochSummary.from_bytes(row[3])

        height_to_hash: Dict[uint32, bytes32] = {}
        sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}

        curr_header_hash = peak
        curr_height = hash_to_height[curr_header_hash]
        while True:
            height_to_hash[curr_height] = curr_header_hash
            if curr_header_hash in hash_to_summary:
                sub_epoch_summaries[curr_height] = hash_to_summary[curr_header_hash]
            if curr_height == 0:
                break
            curr_header_hash = hash_to_prev_hash[curr_header_hash]
            curr_height = hash_to_height[curr_header_hash]

        self.__height_to_hash = height_to_hash
        self.__sub_epoch_summaries = sub_epoch_summaries
        return self

    def update_height(self, height: uint32, header_hash: bytes32, ses: Optional[SubEpochSummary]):
        self.__height_to_hash[height] = header_hash
        if ses is not None:
            self.__sub_epoch_summaries[height] = ses

    def get_hash(self, height: uint32) -> bytes32:
        return self.__height_to_hash[height]

    def contains_height(self, height: uint32) -> bool:
        return height in self.__height_to_hash

    def rollback(self, fork_height: int):
        # fork height may be -1, in which case all blocks are different and we
        # should clear all sub epoch summaries
        heights_to_delete = []
        for ses_included_height in self.__sub_epoch_summaries.keys():
            if ses_included_height > fork_height:
                heights_to_delete.append(ses_included_height)
        for height in heights_to_delete:
            log.info(f"delete ses at height {height}")
            del self.__sub_epoch_summaries[height]

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self.__sub_epoch_summaries[height]

    # TODO: This function is not sustainable
    def get_ses_heights(self) -> List[uint32]:
        return sorted(self.__sub_epoch_summaries.keys())
