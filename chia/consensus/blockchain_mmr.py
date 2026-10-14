from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from chia_rs import BlockRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.block_store_protocol import MMRState
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.coin_commitments import compute_mmr_leaf
from chia.consensus.mmr import MerkleMountainRange

log = logging.getLogger(__name__)


@dataclass
class _CanonicalSnapshot:
    """
    Taken by begin_canonical_update() so a failed canonical update (an
    exception inside the block-store write transaction) can restore the
    in-memory state exactly.
    """

    # flat-node position the update appends from (persisted nodes at and
    # above it are truncated)
    truncation: int
    # the flat nodes a reorg removed at and above `truncation`
    removed: list[bytes32]
    leaf_count: uint32
    last_height: uint32 | None
    last_header_hash: bytes32 | None
    # pending leaves consumed by add_block_to_mmr() during the update
    appended: dict[bytes32, bytes32] = field(default_factory=dict)


@dataclass(repr=False)
class BlockchainMMRManager:
    """
    Manages MMR state for blockchain operations.

    Post-HF2, MMR leaves are composite: H(header_hash || coin_commitments_root).
    The composite leaf of every validated block must be registered via
    register_block_commitment() before the block can be appended to the MMR or
    take part in a speculative MMR rebuild.

    Retention: the canonical MMR (`_mmr`, persisted by the MMR store and
    hydrated at startup) is the source of canonical leaves; a rebuild reads
    them by position. `_block_leaves` only holds *pending* leaves: blocks
    registered but not (yet) appended to this manager's canonical MMR, i.e.
    the blocks of the validation round in progress (a sync batch, a fork being
    validated) and orphans registered since the last canonical commit.
    Appending a block drops its entry; committing a canonical update drops the
    remaining orphans. The map is therefore bounded by the blocks validated
    between two canonical commits, independent of how many orphans peers have
    ever delivered, and so is every copy() taken by an AugmentedBlockchain.

    Evicted leaves are never substituted: a rebuild that needs a leaf that is
    neither in the canonical prefix it reuses nor pending asserts, and the
    callers re-derive such leaves through the replay paths that register them
    (Blockchain.prepare_stored_fork_ancestry for a child of a stored fork,
    FullNode.skip_blocks / Blockchain.run_single_block when a sync resumes a
    stored fork).
    """

    genesis_challenge: bytes32
    _mmr: MerkleMountainRange = field(default_factory=MerkleMountainRange)
    _last_header_hash: bytes32 | None = None
    _last_height: uint32 | None = None
    aggregate_from: uint32 = field(default=uint32(0))  # Height from which to start aggregating blocks into MMR
    # pending composite MMR leaves by block header hash (see the class docstring)
    _block_leaves: dict[bytes32, bytes32] = field(default_factory=dict)
    # None when no canonical update is in progress
    _canonical_snapshot: _CanonicalSnapshot | None = None

    def __repr__(self) -> str:
        return f"BlockchainMMRManager(height={self._last_height}, root={self.compute_current_mmr_root()!r})"

    def copy(self) -> BlockchainMMRManager:
        """Create a deep copy of this MMR manager."""
        new = copy.deepcopy(self)
        # a copy is never part of an in-progress canonical update
        new._canonical_snapshot = None
        return new

    def get_aggrtegate_from(self) -> uint32:
        return self.aggregate_from

    def register_block_commitment(self, header_hash: bytes32, coin_commitments_root: bytes32) -> None:
        """
        Register the composite MMR leaf for a validated block. This does not
        append anything to the MMR; it only makes the leaf available for a
        later canonical append or speculative MMR rebuild, until the block is
        appended or the next canonical update commits.

        Registration is idempotent for the same computed leaf. A conflicting
        leaf for an already-registered block is rejected: the leaf is
        deterministic for a validated block, so a conflict means corruption or
        a caller bug, and silently overwriting it would split the live MMR
        (appended leaf) from future scratch/fork rebuilds (registered leaf).
        """
        leaf = compute_mmr_leaf(header_hash, coin_commitments_root)
        existing = self._block_leaves.get(header_hash)
        if existing is not None:
            assert existing == leaf, f"Conflicting coin commitment registration for block {header_hash.hex()}"
            return
        self._block_leaves[header_hash] = leaf

    def _get_block_leaf(self, header_hash: bytes32) -> bytes32:
        leaf = self._block_leaves.get(header_hash)
        assert leaf is not None, f"Missing coin commitment registration for block {header_hash.hex()}"
        return leaf

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        """
        Add a block to the MMR in sequential order. The block's composite leaf
        must have been registered with register_block_commitment() first; the
        append consumes the pending registration.
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

        # Move the block's composite leaf from the pending map into the MMR
        leaf = self._get_block_leaf(header_hash)
        del self._block_leaves[header_hash]
        if self._canonical_snapshot is not None:
            self._canonical_snapshot.appended[header_hash] = leaf
        self._mmr.append(leaf)
        # Store minimal block info for validation
        self._last_header_hash = header_hash
        self._last_height = height

        log.debug(f"Added block {height} to MMR, new root: {self.compute_current_mmr_root()}")

    def _node_count_at_height(self, height: int) -> int:
        """The flat-node count of an MMR whose leaves are the blocks up to `height`."""
        if height < self.aggregate_from:
            return 0
        leaves = height - self.aggregate_from + 1
        return 2 * leaves - leaves.bit_count()

    def begin_canonical_update(self, fork_height: int, blocks: BlockRecordsProtocol) -> int:
        """
        Begin a canonical MMR update (a canonical append or a reorg), rolling the
        in-memory MMR back to `fork_height` when this is a reorg. Returns the
        flat-node truncation point from which the update appends; the persisted
        node array should be truncated at and above this position.

        Must be paired with commit_canonical_update() once the enclosing database
        transaction commits, or rollback_canonical_update() if it fails.
        """
        assert self._canonical_snapshot is None, "nested canonical MMR update"
        pre_leaf_count = self._mmr.leaf_count
        pre_last_height = self._last_height
        pre_last_header_hash = self._last_header_hash
        if self._last_height is not None and fork_height < self._last_height:
            # reorg: the MMR is truncated back to the fork height
            truncation = self._node_count_at_height(fork_height)
            removed = self._mmr.nodes[truncation:]
            self.rollback_to_height(fork_height, blocks)
            assert len(self._mmr.nodes) == truncation
        else:
            truncation = len(self._mmr.nodes)
            removed = []
        self._canonical_snapshot = _CanonicalSnapshot(
            truncation, removed, pre_leaf_count, pre_last_height, pre_last_header_hash
        )
        return truncation

    def canonical_new_nodes(self, truncation: int) -> list[bytes32]:
        """The flat nodes appended since `truncation` by the in-progress update."""
        return self._mmr.nodes[truncation:]

    def canonical_state(self, canonical_height: uint32, canonical_header_hash: bytes32) -> MMRState:
        """The persistable singleton state for the in-progress canonical update."""
        return MMRState(
            aggregate_from=self.aggregate_from,
            leaf_count=self._mmr.leaf_count,
            canonical_height=canonical_height,
            canonical_header_hash=canonical_header_hash,
        )

    def commit_canonical_update(self) -> None:
        """
        Discard the rollback snapshot after the database transaction commits,
        and drop the pending leaves the update did not append: they belong to
        orphan blocks of the validation round that just ended and are
        re-derivable by the replay paths (see the class docstring). No-op when
        no canonical update was begun (e.g. the block was added as an orphan):
        pending leaves then stay available for a later reorg.
        """
        if self._canonical_snapshot is None:
            return
        self._canonical_snapshot = None
        self._block_leaves.clear()

    def rollback_canonical_update(self) -> None:
        """
        Restore the in-memory MMR (and the pending leaves it consumed) to the
        state before begin_canonical_update(). No-op if the update was already
        committed (the database transaction and the in-memory MMR are then
        both already at the new state).
        """
        snapshot = self._canonical_snapshot
        if snapshot is None:
            return
        del self._mmr.nodes[snapshot.truncation :]
        self._mmr.nodes.extend(snapshot.removed)
        self._mmr.leaf_count = snapshot.leaf_count
        self._last_height = snapshot.last_height
        self._last_header_hash = snapshot.last_header_hash
        self._block_leaves.update(snapshot.appended)
        self._canonical_snapshot = None

    def hydrate(self, nodes: list[bytes32], state: MMRState) -> None:
        """
        Hydrate the in-memory canonical MMR from persisted state. The caller
        must have verified `state` against the canonical peak and the node
        count (the MerkleMountainRange constructor re-validates the node count
        against `leaf_count`). Canonical leaves are served from the hydrated
        MMR by position; nothing is registered as pending.
        """
        self._mmr = MerkleMountainRange(list(nodes), state.leaf_count)
        if state.leaf_count == 0:
            self._last_height = None
            self._last_header_hash = None
            return
        self._last_height = uint32(self.aggregate_from + state.leaf_count - 1)
        self._last_header_hash = state.canonical_header_hash

    def compute_current_mmr_root(self) -> bytes32 | None:
        """Compute the current MMR root representing all blocks added so far."""
        return self._mmr.compute_root()

    def _build_mmr_to_block(
        self, target_block: BlockRecord, blocks: BlockRecordsProtocol, fork_height: int | None
    ) -> bytes32 | None:
        """
        Build an MMR containing all blocks from genesis to target_block (inclusive).

        Canonical leaves (heights up to the common height) are reused from the
        in-memory canonical MMR by position; the remaining leaves must be
        pending in the registration map. A leaf that is neither asserts: the
        canonical leaf at a fork block's height is never substituted.

        Args:
            fork_height: Height of the last block target_block's chain shares
                with the canonical MMR (-1, or anything below aggregate_from,
                when it shares nothing: every leaf then comes from the
                pending map), or None when `blocks` is the canonical chain
                itself (the chain this MMR was built from), in which case the
                root is that of the chain `blocks` describes up to
                target_block's height.
        """
        target_height = target_block.height

        # Case 1: Fast path - current MMR already at target
        if (
            self._last_height is not None
            and self._last_height == target_height
            and self._last_header_hash == target_block.header_hash
        ):
            return self.compute_current_mmr_root()

        # Case 2: no canonical MMR yet; every leaf comes from the pending map
        if self._last_height is None:
            mmr = MerkleMountainRange()
            log.debug(f"Building MMR from height {self.aggregate_from} to {target_height}")
            for height in range(self.aggregate_from, target_height + 1):
                header_hash = blocks.height_to_hash(uint32(height))
                assert header_hash is not None
                mmr.append(self._get_block_leaf(header_hash))
            return mmr.compute_root()

        last_height = self._last_height
        canonical_view = fork_height is None
        if fork_height is None:
            # `blocks` claims to be the canonical chain: it must agree with the
            # MMR at the MMR's tip, or its leaves by position are not its blocks
            assert blocks.height_to_hash(last_height) == self._last_header_hash, (
                f"canonical MMR view mismatch at height {last_height}: "
                f"MMR tip {self._last_header_hash} is not the chain's block {blocks.height_to_hash(last_height)}"
            )
            fork_height = last_height

        # Case 3: reuse the canonical prefix up to the common height, then
        # append the target chain's remaining leaves from the pending map
        common_height: int = min(last_height, target_height, fork_height)
        log.debug(f"Reusing underlying MMR, rollback to {common_height}, then rebuild to {target_height}")

        if common_height < self.aggregate_from:
            mmr = MerkleMountainRange()
            common_height = self.aggregate_from - 1
        else:
            mmr = copy.deepcopy(self._mmr)
            for _ in range(last_height - common_height):
                mmr.pop()

        new_hashes: list[bytes32] = []
        if canonical_view:
            # the chain `blocks` describes, by height
            for height in range(common_height + 1, target_height + 1):
                header_hash = blocks.height_to_hash(uint32(height))
                assert header_hash is not None
                new_hashes.append(header_hash)
        else:
            # the fork chain, walking backward from target to the common height
            current = target_block
            while current.height > common_height:
                new_hashes.append(current.header_hash)
                if current.height == 0:
                    break
                current = blocks.block_record(current.prev_hash)
            new_hashes.reverse()
            if common_height >= self.aggregate_from:
                # the reused canonical prefix must be the fork's actual ancestry
                assert current.height == common_height
                canonical_hash = (
                    self._last_header_hash
                    if common_height == last_height
                    else blocks.height_to_hash(uint32(common_height))
                )
                assert current.header_hash == canonical_hash, (
                    f"canonical MMR view mismatch at height {common_height}: fork ancestor {current.header_hash} "
                    f"is not the canonical block {canonical_hash}"
                )

        for hh in new_hashes:
            mmr.append(self._get_block_leaf(hh))

        return mmr.compute_root()

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: BlockRecordsProtocol,
        fork_height: int | None = None,
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
