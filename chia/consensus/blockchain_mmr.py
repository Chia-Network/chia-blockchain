from __future__ import annotations

import logging
from typing import Any, Optional, Union

from chia_rs import BlockRecord, FullBlock
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
    _last_height: int
    _checkpoints: dict[int, MerkleMountainRange]  # height -> MMR snapshot
    _checkpoint_interval: int
    _max_checkpoints: int

    def __init__(
        self, mmr: Optional[BlockchainMMRManager] = None, checkpoint_interval: int = 1000, max_checkpoints: int = 10
    ) -> None:
        # Current MMR state
        if mmr is not None:
            self._mmr = mmr._mmr.copy()
            self._last_height = mmr._last_height
            self._checkpoints = {h: mmr_snap.copy() for h, mmr_snap in mmr._checkpoints.items()}
            self._checkpoint_interval = mmr._checkpoint_interval
            self._max_checkpoints = mmr._max_checkpoints
        else:
            self._mmr: MerkleMountainRange = MerkleMountainRange.create()
            self._last_height: int = -1
            self._checkpoints: dict[int, MerkleMountainRange] = {}
            self._checkpoint_interval = checkpoint_interval
            self._max_checkpoints = max_checkpoints

    def copy(self) -> BlockchainMMRManager:
        return BlockchainMMRManager(self)

    def add_block_to_mmr(self, block: Union[BlockRecord, FullBlock]) -> None:
        """
        Add a block record to the MMR in sequential order.
        This should be called for blocks in height order to maintain MMR integrity.
        """

        # For blocks loaded from disk during initialization, they might not be in order
        # Only add blocks that are the next expected height
        if block.height == self._last_height + 1:
            # Add block's header hash to the MMR
            self._mmr.append(block.header_hash)
            self._last_height = block.height

            # Create checkpoint if we've reached a checkpoint interval
            if block.height > 0 and block.height % self._checkpoint_interval == 0:
                self._checkpoints[block.height] = self._mmr.copy()
                log.debug(f"Created MMR checkpoint at height {block.height}")

                # Clean up old checkpoints (keep only max_checkpoints to limit memory)
                if len(self._checkpoints) > self._max_checkpoints:
                    oldest_checkpoint = min(self._checkpoints.keys())
                    del self._checkpoints[oldest_checkpoint]
                    log.debug(f"Removed old MMR checkpoint at height {oldest_checkpoint}")

            log.debug(f"Added block {block.height} to MMR, new root: {self._mmr.get_root().hex()}")
        else:
            # Skip blocks that are out of order or duplicate
            log.debug(f"Skipping block height {block.height}, expected {self._last_height + 1}")

    def get_current_mmr_root(self) -> bytes32:
        """Get the current MMR root representing all blocks added so far"""
        return self._mmr.get_root()

    def get_mmr_root_at_height(self, height: int) -> Optional[bytes32]:
        """Get MMR root that should be stored in a block at given height"""
        if height == 0:
            # Genesis block has empty MMR
            return bytes32([0] * 32)

        if height - 1 == self._last_height:
            # If we want MMR root for height N, it should contain blocks 0..N-1
            # And we currently have blocks 0..height-1, so we have the right MMR
            return self._mmr.get_root()

        if height - 1 < self._last_height:
            log.warning(f"Requested MMR root at height {height}, but MMR is at height {self._last_height}")
            return None

        log.warning(f"Requested MMR root at height {height}, but MMR only has blocks up to {self._last_height}")
        return None

    def get_inclusion_proof(self, header_hash: bytes32) -> Optional[tuple[Any, ...]]:
        """Get inclusion proof for a header hash"""
        return self._mmr.get_inclusion_proof(header_hash)

    def verify_inclusion_proof(self, header_hash: bytes32, proof: tuple[Any, ...]) -> bool:
        """Verify inclusion proof against current MMR"""
        if proof is None:
            return False
        peak_index, proof_bytes, other_peak_roots = proof
        return self._mmr.verify_inclusion(header_hash, peak_index, proof_bytes, other_peak_roots)

    def rollback_to_height(self, target_height: int, blocks: BlockRecordsProtocol) -> None:
        """
        Efficiently rollback MMR to a specific height using checkpoints.

        Args:
            target_height: The height to rollback to
            blocks: BlockRecordsProtocol to fetch blocks for rebuilding
        """
        if target_height >= self._last_height:
            # No rollback needed
            return

        if target_height < 0:
            # Reset to genesis
            self._mmr = MerkleMountainRange.create()
            self._last_height = -1
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
            self._last_height = best_checkpoint_height
        else:
            # No suitable checkpoint, start from genesis
            log.debug(f"Rolling back MMR from genesis to height {target_height}")
            self._mmr = MerkleMountainRange.create()
            self._last_height = -1

        # Rebuild from checkpoint/genesis to target height
        for height in range(self._last_height + 1, target_height + 1):
            try:
                block_record = blocks.height_to_block_record(uint32(height))
                self._mmr.append(block_record.header_hash)
                self._last_height = height
            except Exception:
                log.warning(f"Could not find block at height {height} during MMR rollback")
                break

        log.debug(f"MMR rollback completed. Now at height {self._last_height}")


def compute_header_mmr_root(
    height: int,
    prev_block: Optional[BlockRecord],
    blocks: BlockRecordsProtocol,
) -> bytes32:
    """
    Compute the header MMR root for a block at the given height.
    This is a convenience function that tries to use the blockchain's MMR manager if available.
    """
    # For now, this is a simplified implementation
    # In a full implementation, this would use the blockchain's MMR manager

    if height == 0:
        # Genesis block has empty MMR
        return bytes32([0] * 32)

    # Build MMR from genesis to height-1
    mmr = MerkleMountainRange.create()

    # This is a simplified approach - walk backwards from prev_block to collect chain
    chain = []
    current_block = prev_block

    while current_block is not None and current_block.height >= 0:
        chain.append(current_block)
        if current_block.height == 0:
            break
        # Get previous block
        try:
            current_block = blocks.block_record(current_block.prev_hash)
        except Exception:
            break

    # Reverse to get genesis->target order
    chain.reverse()

    # Build MMR with blocks 0 to height-1
    for block in chain:
        if block.height < height:
            mmr.append(block.header_hash)
        if block.height == height - 1:
            break

    return mmr.get_root()


def compute_mmr_root_for_reorg_block(header_block: HeaderBlock, blocks: BlockRecordsProtocol) -> Optional[bytes32]:
    """
    Compute MMR root for a block during reorg validation.
    This builds the MMR by finding the fork point and adding blocks sequentially.
    """

    if header_block.height == 0:
        # Genesis block has empty MMR
        return bytes32([0] * 32)

    # Build chain from current block back to genesis to find the correct chain context
    chain = []
    current_header_hash = header_block.prev_header_hash

    # Walk back from the previous block to build the chain
    for _ in range(header_block.height):  # Prevent infinite loops
        try:
            current_block = blocks.block_record(current_header_hash)
            chain.append(current_block)
            if current_block.height == 0:
                break
            current_header_hash = current_block.prev_hash
        except Exception:
            # If we can't find a block, we can't compute the MMR
            log.warning(f"Could not find block {current_header_hash.hex()} when computing MMR for reorg")
            return None

    # Reverse to get genesis->target order
    chain.reverse()

    # Build MMR with blocks 0 to height-1 (the chain that this block builds upon)
    mmr = MerkleMountainRange.create()
    for block in chain:
        if block.height < header_block.height:
            mmr.append(block.header_hash)

    return mmr.get_root()
