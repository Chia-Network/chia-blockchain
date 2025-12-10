from __future__ import annotations

import logging

from chia_rs import BlockRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.mmr import MerkleMountainRange

log = logging.getLogger(__name__)


class BlockchainMMRManager:
    """
    Manages MMR state for blockchain operations.
    Includes checkpointing for efficient rollback during reorgs.
    """

    _mmr: MerkleMountainRange

    _checkpoints: dict[int, MerkleMountainRange]  # height -> MMR snapshot
    _checkpoint_interval: int
    _max_checkpoints: int

    def __init__(
        self, mmr: BlockchainMMRManager | None = None, checkpoint_interval: int = 1000, max_checkpoints: int = 10
    ) -> None:
        # Current MMR state
        if mmr is not None:
            self._mmr = mmr._mmr.copy()
            self._last_header_hash: bytes32 | None = mmr._last_header_hash
            self._last_height: uint32 | None = mmr._last_height
            self._checkpoints = {h: mmr_snap.copy() for h, mmr_snap in mmr._checkpoints.items()}
            self._checkpoint_interval = mmr._checkpoint_interval
            self._max_checkpoints = mmr._max_checkpoints
        else:
            self._mmr: MerkleMountainRange = MerkleMountainRange()
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
        """

        # Only add blocks that are the next expected height
        if self._last_header_hash is not None and (prev_hash != self._last_header_hash):
            # Skip blocks that are out of order or duplicate
            log.warning(
                f"Skipping block height {height}, prev_hash mismatch "
                f"(expected {self._last_header_hash.hex()[:16]}, got {prev_hash.hex()[:16]})"
            )
            return
        # genesis case is equivilant to normal case
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

        log.debug(f"Added block {height} to MMR, new root: {self._mmr.get_root()}")

    def get_current_mmr_root(self) -> bytes32 | None:
        """Get the current MMR root representing all blocks added so far"""
        return self._mmr.get_root()

    def _build_mmr_to_block(self, target_block: BlockRecord, blocks: BlockRecordsProtocol) -> bytes32 | None:
        """
        Build an MMR containing all blocks from genesis to target_block (inclusive).
        Uses checkpoints or current MMR state when available to avoid rebuilding from genesis.
        """
        target_height = target_block.height

        # Fast path: if current MMR is already at target height, use it directly
        if self._last_height is not None and self._last_height == target_height:
            if self._last_header_hash == target_block.header_hash:
                log.debug(f"Using current MMR state at height {target_height}")
                return self._mmr.get_root()

        # Try to find the best starting point (current MMR or checkpoint)
        best_start_height = -1
        best_mmr = None

        # Check checkpoints - sort in descending order and take first match
        for checkpoint_height in sorted(self._checkpoints.keys(), reverse=True):
            if checkpoint_height <= target_height and checkpoint_height > best_start_height:
                best_start_height = checkpoint_height
                best_mmr = self._checkpoints[checkpoint_height].copy()
                log.debug(f"Using checkpoint at height {checkpoint_height} as starting point")

        # If we have a starting point, use it; otherwise start from genesis
        if best_mmr is not None:
            mmr = best_mmr
            start_height = best_start_height + 1
        else:
            mmr = MerkleMountainRange()
            start_height = 0
            log.debug(f"Building MMR from genesis to {target_height}")

        # Append remaining blocks from start_height to target_height
        for height in range(start_height, target_height + 1):
            block = blocks.height_to_block_record(uint32(height))
            mmr.append(block.header_hash)

        return mmr.get_root()

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32 | None,
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: BlockRecordsProtocol,
    ) -> bytes32 | None:
        """
        Compute MMR root for a block with sp/slot filtering.

        Works for both block validation and creation by computing finalized blocks
        relative to the given sp/slot parameters.
        """
        if prev_header_hash is None:
            # Genesis block has empty MMR
            return None

        prev_block = blocks.block_record(prev_header_hash)

        if starts_new_slot:
            # New slot - all blocks up to and including prev_block are finalized
            mmr_root = self._build_mmr_to_block(prev_block, blocks)
            log.debug(f"New slot: Built MMR with all blocks up to height {prev_block.height}")
            return mmr_root

        # Same slot - need to find cutoff based on sp_index
        # Walk backwards from prev_block to find highest finalized block
        current = prev_block
        cutoff_block = None

        while True:
            # Check if prev is finalized relative to new block:
            # 1. Earlier signage point
            if current.signage_point_index < new_sp_index:
                cutoff_block = current
                log.debug(
                    f"Found earlier sp at height {current.height} "
                    f"(sp={current.signage_point_index} < {new_sp_index}), cutoff at {current.height}"
                )
                break

            # TODO: do we include all from genesis or from the fork point?
            if current.height == 0:
                # Reached genesis without finding cutoff
                break

            # 2. Crossed slot boundary
            if current.first_in_sub_slot:
                cutoff_block = blocks.block_record(current.prev_hash)
                log.debug(
                    f"Found slot boundary at height {current.height}, "
                    f"cutoff at {current.height - 1} for new block (sp={new_sp_index})"
                )
                break

            current = blocks.block_record(current.prev_hash)

        if cutoff_block is None:
            # No finalized blocks
            log.debug(f"No finalized blocks for new block (sp={new_sp_index})")
            return None

        # Build MMR from genesis to cutoff block
        mmr_root = self._build_mmr_to_block(cutoff_block, blocks)
        log.debug(
            f"Built MMR for new block (sp={new_sp_index}) with finalized blocks "
            f"(cutoff at height {cutoff_block.height})"
        )

        return mmr_root

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
            self._mmr = MerkleMountainRange()
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
            self._mmr = MerkleMountainRange()
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
