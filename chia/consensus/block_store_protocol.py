from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, Optional, Protocol

from chia_rs import BlockRecord, FullBlock, SubEpochChallengeSegment
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


class BlockStoreProtocol(Protocol):
    """
    Protocol defining the interface for BlockStore.
    This is a substitute for importing from chia.full_node.block_store directly.
    """

    async def start_transaction(self) -> Coroutine[Any, None, None]:
        """Context manager for a database transaction."""
        pass

    async def add_full_block(self, header_hash: bytes32, block: FullBlock, block_record: BlockRecord) -> None:
        """
        Adds a full block to the database along with block record
        """
        pass

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        """
        Returns a full block by header hash
        """
        pass

    async def get_full_block_bytes(self, header_hash: bytes32) -> Optional[bytes]:
        """
        Returns a serialized full block by header hash
        """
        pass

    async def get_full_blocks_at(self, heights: list[uint32]) -> list[FullBlock]:
        """
        Returns a list of blocks at the specified heights
        """
        pass

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        """
        Returns a block record by header hash
        """
        pass

    async def get_block_records_by_hash(self, header_hashes: list[bytes32]) -> list[BlockRecord]:
        """
        Returns a dictionary of header hashes to block records
        """
        pass

    async def get_block_records_in_range(self, start: int, stop: int) -> dict[bytes32, BlockRecord]:
        """
        Returns a dictionary of header hashes to block records in the given range
        """
        pass

    async def get_block_records_close_to_peak(
        self, blocks_n: int
    ) -> tuple[dict[bytes32, BlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary of header hashes to block records close to the peak
        """
        pass

    async def get_prev_hash(self, header_hash: bytes32) -> bytes32:
        """
        Returns the previous hash of a block
        """
        pass

    async def set_peak(self, header_hash: bytes32) -> None:
        """
        Sets the peak block hash
        """
        pass

    async def get_peak(self) -> Optional[tuple[bytes32, uint32]]:
        """
        Returns the peak block hash
        """
        pass

    async def set_in_chain(self, header_hashes: list[tuple[bytes32]]) -> None:
        """
        Sets blocks as part of the blockchain
        """
        pass

    async def get_generator(self, header_hash: bytes32) -> Optional[bytes]:
        """
        Returns the generator for a block
        """
        pass

    async def get_generators_at(self, heights: set[uint32]) -> dict[uint32, bytes]:
        """
        Returns the generators for the blocks at specified heights
        """
        pass

    def rollback_cache_block(self, header_hash: bytes32) -> None:
        """
        Rolls back a block from the cache
        """
        pass

    async def rollback(self, height: int) -> None:
        """
        Rolls back blocks to a specific height
        """
        pass

    async def get_blocks_by_hash(self, header_hashes: list[bytes32]) -> list[FullBlock]:
        """
        Returns a list of full blocks by header hashes
        """
        pass

    async def replace_proof(self, header_hash: bytes32, block: FullBlock) -> None:
        """
        Replaces a VDF proof
        """
        pass

    async def persist_sub_epoch_challenge_segments(
        self, sub_epoch_summary_hash: bytes32, segments: list[SubEpochChallengeSegment]
    ) -> None:
        """
        Persists sub-epoch challenge segments
        """
        pass

    async def get_sub_epoch_challenge_segments(
        self, sub_epoch_summary_hash: bytes32
    ) -> Optional[list[SubEpochChallengeSegment]]:
        """
        Returns sub-epoch challenge segments by sub-epoch summary hash
        """
        pass
