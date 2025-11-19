from __future__ import annotations

import logging
from typing import Any, Optional

from chia_rs import BlockRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.mmr import MerkleMountainRange

log = logging.getLogger(__name__)


class BlockchainMMRManager:
    """
    Manages MMR state for blockchain operations.
    Tracks MMR of header hashes for proof of weight.
    Includes checkpointing system for efficient rollback during reorgs.
    """

    _mmr: MerkleMountainRange
    _last_block: Optional[BlockRecord]
    _checkpoints: dict[int, MerkleMountainRange]  # height -> MMR snapshot
    _checkpoint_interval: int
    _max_checkpoints: int

    def __init__(
        self, mmr: Optional[BlockchainMMRManager] = None, checkpoint_interval: int = 1000, max_checkpoints: int = 10
    ) -> None:
        # Current MMR state
        if mmr is not None:
            self._mmr = mmr._mmr.copy()
            self._last_header_hash: Optional[bytes32] = mmr._last_header_hash
            self._last_height: Optional[uint32] = mmr._last_height
            self._checkpoints = {h: mmr_snap.copy() for h, mmr_snap in mmr._checkpoints.items()}
            self._checkpoint_interval = mmr._checkpoint_interval
            self._max_checkpoints = mmr._max_checkpoints
        else:
            self._mmr: MerkleMountainRange = MerkleMountainRange.create()
            self._last_header_hash = None
            self._last_height = None
            self._checkpoints: dict[int, MerkleMountainRange] = {}
            self._checkpoint_interval = checkpoint_interval
            self._max_checkpoints = max_checkpoints

    def copy(self) -> BlockchainMMRManager:
        return BlockchainMMRManager(self)

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        """
        Add a block to the MMR in sequential order.
        This should be called for blocks in height order to maintain MMR integrity.

        Args:
            header_hash: Hash of the block header
            prev_hash: Hash of the previous block header
            height: Block height
        """

        # For blocks loaded from disk during initialization, they might not be in order
        # Only add blocks that are the next expected height

        # TODO v2_WP handle genesis block properly
        if self._last_header_hash is not None and (prev_hash != self._last_header_hash):
            # Skip blocks that are out of order or duplicate
            log.warning(
                f"Skipping block height {height}, prev_hash mismatch "
                f"(expected {self._last_header_hash.hex()[:16]}, got {prev_hash.hex()[:16]})"
            )
            return
        assert self._last_height is None or height == self._last_height + 1
        # Add block's header hash to the MMR
        self._mmr.append(header_hash)
        # Store minimal block info for validation
        self._last_header_hash = header_hash
        self._last_height = height

        # Create checkpoint if we've reached a checkpoint interval
        if height > 0 and height % self._checkpoint_interval == 0:
            self._checkpoints[height] = self._mmr.copy()
            log.debug(f"Created MMR checkpoint at height {height}")

            # Clean up old checkpoints (keep only max_checkpoints to limit memory)
            if len(self._checkpoints) > self._max_checkpoints:
                oldest_checkpoint = min(self._checkpoints.keys())
                del self._checkpoints[oldest_checkpoint]
                log.debug(f"Removed old MMR checkpoint at height {oldest_checkpoint}")

        log.debug(f"Added block {height} to MMR, new root: {self._mmr.get_root().hex()}")

    def get_current_mmr_root(self) -> bytes32:
        """Get the current MMR root representing all blocks added so far"""
        return self._mmr.get_root()

    def get_inclusion_proof(self, header_hash: bytes32) -> Optional[tuple[Any, ...]]:
        """Get inclusion proof for a header hash"""
        return self._mmr.get_inclusion_proof(header_hash)

    def verify_inclusion_proof(self, header_hash: bytes32, proof: tuple[Any, ...]) -> bool:
        """Verify inclusion proof against current MMR"""
        if proof is None:
            return False
        peak_index, proof_bytes, other_peak_roots = proof
        return self._mmr.verify_inclusion(header_hash, peak_index, proof_bytes, other_peak_roots)

    def get_mmr_root_for_block(
        self,
        prev_header_hash: Optional[bytes32],
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: BlockRecordsProtocol,
    ) -> bytes32:
        """
        Compute MMR root for a block with sp/slot filtering.

        Works for both block validation and creation by computing finalized blocks
        relative to the given sp/slot parameters.

        Args:
            prev_header_hash: Header hash of previous block (None for genesis)
            new_sp_index: Signage point index of the block
            starts_new_slot: True if block starts a new slot (len(finished_sub_slots) > 0)
            blocks: BlockRecordsProtocol to walk the chain

        Returns:
            MMR root containing only finalized blocks relative to block's sp/slot
        """
        if prev_header_hash is None:
            # Genesis block has empty MMR
            return bytes32([0] * 32)

        prev_block = blocks.block_record(prev_header_hash)

        if starts_new_slot:
            # New slot - all blocks up to and including prev_block are finalized
            # Collect all blocks from genesis to prev_block
            chain_blocks = []
            current = prev_block
            while current.height >= 0:
                chain_blocks.append(current)
                if current.height == 0:
                    break
                current = blocks.block_record(current.prev_hash)
            chain_blocks.reverse()

            # Build MMR
            filtered_mmr = MerkleMountainRange.create()
            for block in chain_blocks:
                filtered_mmr.append(block.header_hash)

            log.debug(f"New slot: Built MMR with all {len(chain_blocks)} blocks up to height {prev_block.height}")

            return filtered_mmr.get_root()

        # Same slot - need to find cutoff based on sp_index
        # Walk backwards from prev_block to find highest finalized block
        current = prev_block
        cutoff_block = None

        while current.height > 0:
            prev = blocks.block_record(current.prev_hash)

            # Check if prev is finalized relative to new block:
            # 1. Crossed slot boundary
            if current.first_in_sub_slot:
                cutoff_block = prev
                log.debug(
                    f"Found slot boundary at height {current.height}, "
                    f"cutoff at {prev.height} for new block (sp={new_sp_index})"
                )
                break

            # 2. Earlier signage point
            if prev.signage_point_index < new_sp_index:
                cutoff_block = prev
                log.debug(
                    f"Found earlier sp at height {prev.height} "
                    f"(sp={prev.signage_point_index} < {new_sp_index}), cutoff at {prev.height}"
                )
                break

            current = prev

        if cutoff_block is None:
            # No finalized blocks
            log.debug(f"No finalized blocks for new block (sp={new_sp_index})")
            return bytes32([0] * 32)

        # Collect all blocks from genesis to cutoff
        chain_blocks = []
        current = cutoff_block
        while current.height > 0:
            chain_blocks.append(current)
            current = blocks.block_record(current.prev_hash)
        chain_blocks.append(current)  # Add genesis
        chain_blocks.reverse()

        # Build MMR
        filtered_mmr = MerkleMountainRange.create()
        for block in chain_blocks:
            filtered_mmr.append(block.header_hash)

        log.debug(
            f"Built MMR for new block (sp={new_sp_index}) with {len(chain_blocks)} finalized blocks "
            f"(cutoff at height {cutoff_block.height})"
        )

        return filtered_mmr.get_root()

    def rollback_to_height(self, target_height: int, blocks: BlockRecordsProtocol) -> None:
        """
        Efficiently rollback MMR to a specific height using checkpoints.

        Args:
            target_height: The height to rollback to
            blocks: BlockRecordsProtocol to fetch blocks for rebuilding
        """
        current_height = self._last_height if self._last_height is not None else -1

        if target_height >= current_height:
            # No rollback needed
            return

        if target_height == 0:
            # Reset to genesis
            self._mmr = MerkleMountainRange.create()
            self._last_block = None
            return

        # Find the best checkpoint to start from
        best_checkpoint_height = -1
        for checkpoint_height in self._checkpoints.keys():
            if checkpoint_height <= target_height and checkpoint_height > best_checkpoint_height:
                best_checkpoint_height = checkpoint_height

        if best_checkpoint_height >= 0:
            # Start from checkpoint
            log.debug(f"Rolling back MMR from checkpoint at height {best_checkpoint_height} to {target_height}")
            self._mmr = self._checkpoints[best_checkpoint_height].copy()
            start_height = best_checkpoint_height + 1
        else:
            # No suitable checkpoint, start from genesis
            log.debug(f"Rolling back MMR from genesis to height {target_height}")
            self._mmr = MerkleMountainRange.create()
            start_height = 0

        # Rebuild from checkpoint/genesis to target height
        self._last_header_hash = None
        self._last_height = None
        for height in range(start_height, target_height + 1):
            try:
                block_record = blocks.height_to_block_record(uint32(height))
                self._mmr.append(block_record.header_hash)
                self._last_header_hash = block_record.header_hash
                self._last_height = uint32(height)
            except Exception:
                log.warning(f"Could not find block at height {height} during MMR rollback")
                break

        final_height = self._last_height if self._last_height is not None else -1
        log.debug(f"MMR rollback completed. Now at height {final_height}")
