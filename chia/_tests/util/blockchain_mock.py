from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia_rs import BlockRecord, HeaderBlock, SubEpochChallengeSegment, SubEpochSegments, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.types.blockchain_format.vdf import VDFInfo


# implements BlockchainInterface
class BlockchainMock:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlocksProtocol

        _protocol_check: ClassVar[BlocksProtocol] = cast("BlockchainMock", None)

    def __init__(
        self,
        blocks: dict[bytes32, BlockRecord],
        headers: Optional[dict[bytes32, HeaderBlock]] = None,
        height_to_hash: Optional[dict[uint32, bytes32]] = None,
        sub_epoch_summaries: Optional[dict[uint32, SubEpochSummary]] = None,
    ):
        if sub_epoch_summaries is None:
            sub_epoch_summaries = {}
        if height_to_hash is None:
            height_to_hash = {}
        if headers is None:
            headers = {}
        self._block_records = blocks
        self._headers = headers
        self._height_to_hash = height_to_hash
        self._sub_epoch_summaries = sub_epoch_summaries
        self._sub_epoch_segments: dict[bytes32, SubEpochSegments] = {}
        self.log = logging.getLogger(__name__)

    def get_peak(self) -> Optional[BlockRecord]:
        return None

    def get_peak_height(self) -> Optional[uint32]:
        return None

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._block_records[header_hash]

    def height_to_block_record(self, height: uint32, check_db: bool = False) -> BlockRecord:
        # Precondition: height is < peak height

        header_hash: Optional[bytes32] = self.height_to_hash(height)
        assert header_hash is not None

        return self.block_record(header_hash)

    def get_ses_heights(self) -> list[uint32]:
        return sorted(self._sub_epoch_summaries.keys())

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self._sub_epoch_summaries[height]

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        assert height in self._height_to_hash
        return self._height_to_hash[height]

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        block_hash_from_hh = self.height_to_hash(height)
        if block_hash_from_hh is None or block_hash_from_hh != header_hash:
            return False
        return True

    async def contains_block_from_db(self, header_hash: bytes32) -> bool:
        return header_hash in self._block_records

    def contains_height(self, height: uint32) -> bool:
        return height in self._height_to_hash

    async def warmup(self, fork_point: uint32) -> None:
        return

    async def get_block_records_in_range(self, start: int, stop: int) -> dict[bytes32, BlockRecord]:
        return self._block_records

    async def get_block_records_at(self, heights: list[uint32]) -> list[BlockRecord]:
        block_records: list[BlockRecord] = []
        for height in heights:
            block_records.append(self.height_to_block_record(height))
        return block_records

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        return self._block_records.get(header_hash)

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        return self._block_records[header_hash]

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        ret = []
        for h in header_hashes:
            ret.append(self._block_records[h].prev_hash)
        return ret

    def remove_block_record(self, header_hash: bytes32) -> None:
        del self._block_records[header_hash]

    def add_block_record(self, block: BlockRecord) -> None:
        self._block_records[block.header_hash] = block

    async def get_header_blocks_in_range(
        self, start: int, stop: int, tx_filter: bool = True
    ) -> dict[bytes32, HeaderBlock]:
        return self._headers

    async def persist_sub_epoch_challenge_segments(
        self, sub_epoch_summary_hash: bytes32, segments: list[SubEpochChallengeSegment]
    ) -> None:
        self._sub_epoch_segments[sub_epoch_summary_hash] = SubEpochSegments(segments)

    async def get_sub_epoch_challenge_segments(
        self,
        sub_epoch_summary_hash: bytes32,
    ) -> Optional[list[SubEpochChallengeSegment]]:
        segments = self._sub_epoch_segments.get(sub_epoch_summary_hash)
        if segments is None:
            return None
        return segments.challenge_segments

    def seen_compact_proofs(self, vdf_info: VDFInfo, height: uint32) -> bool:
        return False

    async def lookup_block_generators(self, header_hash: bytes32, generator_refs: set[uint32]) -> dict[uint32, bytes]:
        # not implemented
        assert False  # pragma: no cover
