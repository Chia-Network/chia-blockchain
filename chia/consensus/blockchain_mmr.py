from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from chia_rs import BlockRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint128

from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.coin_commitments import compute_mmr_leaf
from chia.consensus.mmr import MerkleMountainRange

log = logging.getLogger(__name__)


@dataclass(repr=False)
class BlockchainMMRManager:
    """
    Manages MMR state for blockchain operations.

    `_mmr` holds the canonical chain's leaves; a fork's leaves are built from
    its ForkInfo.
    """

    genesis_challenge: bytes32
    _mmr: MerkleMountainRange = field(default_factory=MerkleMountainRange)
    _last_header_hash: bytes32 | None = None
    _last_height: uint32 | None = None
    aggregate_from: uint32 = field(default=uint32(0))  # Height from which to start aggregating blocks into MMR

    def __repr__(self) -> str:
        return f"BlockchainMMRManager(height={self._last_height}, root={self.compute_current_mmr_root()!r})"

    def get_aggrtegate_from(self) -> uint32:
        return self.aggregate_from

    def add_block_to_mmr(
        self, header_hash: bytes32, prev_hash: bytes32, height: uint32, coin_commitments_root: bytes32 | None
    ) -> None:
        """
        Add a block to the MMR in sequential order. `coin_commitments_root` is
        None only below aggregate_from.
        """
        if height < self.aggregate_from:
            return
        assert coin_commitments_root is not None

        # Only add blocks that are the next expected height.
        if self._last_header_hash is None:
            assert self._last_height is None
            assert height == self.aggregate_from
        else:
            assert prev_hash == self._last_header_hash
            assert self._last_height is not None
            assert height == self._last_height + 1

        self._mmr.append(compute_mmr_leaf(header_hash, coin_commitments_root))
        # Store minimal block info for validation
        self._last_header_hash = header_hash
        self._last_height = height

        log.debug(f"Added block {height} to MMR, new root: {self.compute_current_mmr_root()}")

    def compute_current_mmr_root(self) -> bytes32 | None:
        """Compute the current MMR root representing all blocks added so far."""
        return self._mmr.compute_root()

    def _build_mmr_to_block(
        self, target_block: BlockRecord, blocks: BlockRecordsProtocol, fork_info: ForkInfo | None
    ) -> bytes32 | None:
        """
        Build an MMR containing all blocks from genesis to target_block (inclusive).

        Leaves up to the fork point are reused from the canonical MMR by
        position; leaves after it are built from fork_info.

        Args:
            fork_info: target_block's chain from its fork point, or None when
                target_block is canonical.
        """
        target_height = target_block.height

        # Fast path - current MMR already at target
        if (
            self._last_height is not None
            and self._last_height == target_height
            and self._last_header_hash == target_block.header_hash
        ):
            return self.compute_current_mmr_root()

        # the last height whose leaf comes from the canonical MMR
        prefix_height = target_height if fork_info is None else min(fork_info.fork_height, target_height)
        if prefix_height < self.aggregate_from:
            mmr = MerkleMountainRange()
        else:
            last_height = self._last_height
            assert last_height is not None and prefix_height <= last_height
            # `blocks` must agree with the MMR at the MMR's tip, or its leaves
            # by position are not its blocks
            assert blocks.height_to_hash(last_height) == self._last_header_hash, (
                f"canonical MMR view mismatch at height {last_height}: "
                f"MMR tip {self._last_header_hash} is not the chain's block {blocks.height_to_hash(last_height)}"
            )
            if fork_info is not None:
                # the reused canonical prefix must be the fork's actual
                # ancestry; a reorg committed since fork_info was built may
                # have replaced its common ancestor
                if target_height <= fork_info.fork_height:
                    ancestor = target_block.header_hash
                else:
                    ancestor = blocks.block_record(fork_info.block_hashes[0]).prev_hash
                canonical_hash = blocks.height_to_hash(uint32(prefix_height))
                assert ancestor == canonical_hash, (
                    f"canonical MMR view mismatch at height {prefix_height}: fork ancestor {ancestor} "
                    f"is not the canonical block {canonical_hash}"
                )
            log.debug(f"Reusing underlying MMR, rollback to {prefix_height}, then rebuild to {target_height}")
            mmr = copy.deepcopy(self._mmr)
            for _ in range(last_height - prefix_height):
                mmr.pop()

        if fork_info is not None and target_height > fork_info.fork_height:
            last_index = target_height - fork_info.fork_height - 1
            assert fork_info.block_hashes[last_index] == target_block.header_hash
            for height in range(max(fork_info.fork_height + 1, self.aggregate_from), target_height + 1):
                index = height - fork_info.fork_height - 1
                coin_commitments_root = fork_info.commitment_roots[index]
                assert coin_commitments_root is not None
                mmr.append(compute_mmr_leaf(fork_info.block_hashes[index], coin_commitments_root))

        return mmr.compute_root()

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        sp_total_iters: uint128,
        blocks: BlockRecordsProtocol,
        fork_info: ForkInfo | None = None,
    ) -> bytes32 | None:
        """
        Compute the MMR root containing blocks infused before the signage point.

        Works for both block validation and creation by computing the finalized
        cutoff relative to the signage point's absolute total iterations.
        `fork_info` describes the chain prev_header_hash is on; None means the
        canonical chain.
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
        mmr_root = self._build_mmr_to_block(cutoff_block, blocks, fork_info)
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
