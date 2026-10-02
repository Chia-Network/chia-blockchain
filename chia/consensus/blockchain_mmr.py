from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from chia_rs import BlockRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint128

from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.mmr import MerkleMountainRange

log = logging.getLogger(__name__)


@dataclass(repr=False)
class BlockchainMMRManager:
    """
    Manages MMR state for blockchain operations.
    """

    genesis_challenge: bytes32
    _mmr: MerkleMountainRange = field(default_factory=MerkleMountainRange)
    _last_header_hash: bytes32 | None = None
    _last_height: uint32 | None = None
    aggregate_from: uint32 = field(default=uint32(0))  # Height from which to start aggregating blocks into MMR

    def __repr__(self) -> str:
        return f"BlockchainMMRManager(height={self._last_height}, root={self.compute_current_mmr_root()!r})"

    def copy(self) -> BlockchainMMRManager:
        """Create a deep copy of this MMR manager."""
        return copy.deepcopy(self)

    def get_aggrtegate_from(self) -> uint32:
        return self.aggregate_from

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        """
        Add a block to the MMR in sequential order.
        """
        if height < self.aggregate_from:
            return

        # Only add blocks that are the next expected height.
        if self._last_header_hash is None:
            assert self._last_height is None
            assert height == self.aggregate_from
        else:
            assert prev_hash == self._last_header_hash
            assert self._last_height is not None
            assert height == self._last_height + 1

        # Add block's header hash to the MMR
        self._mmr.append(header_hash)
        # Store minimal block info for validation
        self._last_header_hash = header_hash
        self._last_height = height

        log.debug(f"Added block {height} to MMR, new root: {self.compute_current_mmr_root()}")

    def compute_current_mmr_root(self) -> bytes32 | None:
        """Compute the current MMR root representing all blocks added so far."""
        return self._mmr.compute_root()

    def _build_mmr_to_block(
        self, target_block: BlockRecord, blocks: BlockRecordsProtocol, fork_height: uint32 | None
    ) -> bytes32 | None:
        """
        Build an MMR containing all blocks from genesis to target_block (inclusive).

        Args:
            fork_height: Height of last common block, or None for fork at/before genesis
        """
        target_height = target_block.height

        # Case 1: Fast path - current MMR already at target
        if (
            self._last_height is not None
            and self._last_height == target_height
            and self._last_header_hash == target_block.header_hash
        ):
            return self.compute_current_mmr_root()

        # Case 2: Build from scratch when we don't have usable fork context
        if self._last_height is None or fork_height is None:
            mmr = MerkleMountainRange()
            log.debug(f"Building MMR from height {self.aggregate_from} to {target_height}")

            for height in range(self.aggregate_from, target_height + 1):
                header_hash = blocks.height_to_hash(uint32(height))
                assert header_hash is not None
                mmr.append(header_hash)

            return mmr.compute_root()

        # Case 3: rollback to common point and extend via prev-hash walk
        common_height = min(self._last_height, target_height, fork_height)
        log.debug(f"Reusing underlying MMR, rollback to {common_height}, then rebuild to {target_height}")

        if common_height < self.aggregate_from:
            mmr = MerkleMountainRange()
            common_height = uint32(self.aggregate_from - 1)
        else:
            mmr = copy.deepcopy(self._mmr)
            if self._last_height > common_height:
                for _ in range(self._last_height - common_height):
                    mmr.pop()

        # Add fork chain blocks by walking backward from target.
        new_hashes: list[bytes32] = []
        current = target_block
        while current.height > common_height:
            new_hashes.append(current.header_hash)
            if current.height == 0:
                break
            current = blocks.block_record(current.prev_hash)
        new_hashes.reverse()

        for hh in new_hashes:
            mmr.append(hh)

        return mmr.compute_root()

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        sp_total_iters: uint128,
        blocks: BlockRecordsProtocol,
        fork_height: uint32 | None = None,
    ) -> bytes32 | None:
        """
        Compute the MMR root containing blocks infused before the signage point.

        Works for both block validation and creation by computing the finalized
        cutoff relative to the signage point's absolute total iterations.
        """
        if prev_header_hash == self.genesis_challenge:
            # Genesis block has empty MMR
            return None

        cutoff_block = blocks.block_record(prev_header_hash)
        while cutoff_block.total_iters >= sp_total_iters:
            if cutoff_block.height == 0:
                log.debug(f"No blocks infused before signage point at total iterations {sp_total_iters}")
                return None
            cutoff_block = blocks.block_record(cutoff_block.prev_hash)

        # Build MMR from genesis to cutoff block
        mmr_root = self._build_mmr_to_block(cutoff_block, blocks, fork_height)
        log.debug(
            f"Built MMR for signage point at total iterations {sp_total_iters} (cutoff at height {cutoff_block.height})"
        )

        return mmr_root

    def rollback_to_height(self, target_height: int, blocks: BlockRecordsProtocol) -> None:
        """
        rollback MMR to a specific height.
        """
        current_height = self._last_height if self._last_height is not None else -1

        if target_height < 0 or target_height < self.aggregate_from:
            self._mmr = MerkleMountainRange()
            self._last_header_hash = None
            self._last_height = None
            return

        assert self.aggregate_from < current_height

        assert target_height < current_height

        # Pop blocks one by one until we reach target height
        blocks_to_pop = current_height - target_height
        log.debug(f"Rolling back MMR from height {current_height} to {target_height} ({blocks_to_pop} pops)")

        for _ in range(blocks_to_pop):
            self._mmr.pop()

        target_block = blocks.height_to_block_record(uint32(target_height))
        self._last_header_hash = target_block.header_hash
        self._last_height = uint32(target_height)
        log.debug(f"MMR rolled back to height {self._last_height}")
