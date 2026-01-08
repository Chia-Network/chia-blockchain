from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from chia_rs import BlockRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

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
        return f"BlockchainMMRManager(height={self._last_height}, root={self.get_current_mmr_root()!r})"

    def copy(self) -> BlockchainMMRManager:
        """Create a deep copy of this MMR manager."""
        return copy.deepcopy(self)

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        """
        Add a block to the MMR in sequential order.
        """
        if height < self.aggregate_from:
            return

        # Only add blocks that are the next expected height
        assert self._last_header_hash is None or (prev_hash == self._last_header_hash)
        # Add block's header hash to the MMR
        self._mmr.append(header_hash)
        # Store minimal block info for validation
        self._last_header_hash = header_hash
        self._last_height = height

        log.debug(f"Added block {height} to MMR, new root: {self._mmr.get_root()}")

    def get_current_mmr_root(self) -> bytes32 | None:
        """Get the current MMR root representing all blocks added so far"""
        return self._mmr.get_root()

    def _build_mmr_to_block(
        self, target_block: BlockRecord, blocks: BlockRecordsProtocol, fork_height: uint32 | None
    ) -> bytes32 | None:
        """
        Build an MMR containing all blocks from genesis to target_block (inclusive).

        Args:
            fork_height: Height of last common block, or None for fork at/before genesis
        """
        target_height = target_block.height

        # Case 1: Build from scratch
        # (no fork / fork before aggregate_from / underlying MMR doesn't exist/reach fork point)
        if (
            fork_height is None
            or self._last_height is None
            or self._last_height < fork_height
            or fork_height < self.aggregate_from
        ):
            mmr = MerkleMountainRange()
            log.debug(f"Building MMR from height {self.aggregate_from} to {target_height}")

            for height in range(self.aggregate_from, target_height + 1):
                header_hash = blocks.height_to_hash(uint32(height))
                assert header_hash is not None
                mmr.append(header_hash)

            return mmr.get_root()

        # Case 2: Fast path - current MMR already at target (main chain, no fork before target)
        if (
            self._last_height == target_height
            and self._last_header_hash == target_block.header_hash
            and fork_height == target_height
        ):
            log.debug(f"Using current MMR state at height {target_height} (no fork before target)")
            return self._mmr.get_root()

        # Case 3: rollback to fork point and extend
        log.debug(f"Reusing underlying MMR, will rollback to fork {fork_height}, then rebuild to {target_height}")
        mmr = copy.deepcopy(self._mmr)

        # Rollback to fork point if underlying MMR is beyond it
        if self._last_height > fork_height:
            blocks_to_pop = self._last_height - fork_height
            for _ in range(blocks_to_pop):
                mmr.pop()

        # Add blocks from fork point to target
        start_height = max(fork_height + 1, self.aggregate_from)
        for height in range(start_height, target_height + 1):
            header_hash = blocks.height_to_hash(uint32(height))
            assert header_hash is not None
            mmr.append(header_hash)

        return mmr.get_root()

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: BlockRecordsProtocol,
        fork_height: uint32 | None = None,
    ) -> bytes32 | None:
        """
        Compute MMR root for a block with sp/slot filtering.

        Works for both block validation and creation by computing finalized blocks
        relative to the given sp/slot parameters.
        """
        if prev_header_hash == self.genesis_challenge:
            # Genesis block has empty MMR
            return None

        prev_block = blocks.block_record(prev_header_hash)

        if starts_new_slot:
            # New slot - all blocks up to and including prev_block are finalized
            mmr_root = self._build_mmr_to_block(prev_block, blocks, fork_height)
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
        mmr_root = self._build_mmr_to_block(cutoff_block, blocks, fork_height)
        log.debug(
            f"Built MMR for new block (sp={new_sp_index}) with finalized blocks "
            f"(cutoff at height {cutoff_block.height})"
        )

        return mmr_root

    def rollback_to_height(self, target_height: int, blocks: BlockRecordsProtocol) -> None:
        """
        rollback MMR to a specific height.
        """
        current_height = self._last_height if self._last_height is not None else -1

        if target_height < 0:
            # Reset to before genesis (empty MMR)
            self._mmr = MerkleMountainRange()
            self._last_header_hash = None
            self._last_height = None
            return

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
