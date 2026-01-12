from __future__ import annotations

import logging
import random
import time

import pytest
from chia_rs import BlockRecord, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_mmr import BlockchainMMRManager
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.mmr import (
    MerkleMountainRange,
    get_height,
    get_peak_positions,
    leaf_index_to_pos,
    verify_mmr_inclusion,
)
from chia.util.block_cache import BlockCache

logger = logging.getLogger(__name__)


def test_empty_mmr_root() -> None:
    mmr = MerkleMountainRange()
    assert mmr.compute_root() is None  # Empty MMR returns None
    # Note: get_inclusion_proof not yet implemented
    # assert mmr.get_inclusion_proof(random_bytes32()) is None


def test_single_leaf() -> None:
    mmr = MerkleMountainRange()
    leaf = bytes32.random()
    mmr.append(leaf)
    root = mmr.compute_root()
    assert root is not None
    proof = mmr.get_inclusion_proof_by_index(0)
    assert proof is not None
    peak_index, proof_bytes, other_peaks, peak = proof
    assert verify_mmr_inclusion(root, leaf, peak_index, proof_bytes, other_peaks, peak)


def test_multiple_leaves() -> None:
    mmr = MerkleMountainRange()
    leaves = [bytes32.random() for _ in range(10)]
    for leaf in leaves:
        mmr.append(leaf)
    root = mmr.compute_root()
    assert root is not None
    for idx, leaf in enumerate(leaves):
        proof = mmr.get_inclusion_proof_by_index(idx)
        assert proof is not None
        peak_index, proof_bytes, other_peaks, peak = proof
        assert verify_mmr_inclusion(root, leaf, peak_index, proof_bytes, other_peaks, peak)
    # Root should be stable
    mmr2 = MerkleMountainRange()
    for leaf in leaves:
        mmr2.append(leaf)
    root2 = mmr2.compute_root()
    for i in range(10):
        assert mmr.nodes[i] == mmr2.nodes[i]
    assert root2 == root


def test_duplicate_leaves() -> None:
    mmr = MerkleMountainRange()
    leaf = bytes32.random()
    for _ in range(3):
        mmr.append(leaf)
    # All should be provable by index
    for i in range(3):
        proof = mmr.get_inclusion_proof_by_index(i)
        assert proof is not None
        peak_index, proof_bytes, other_peaks, peak = proof
        root = mmr.compute_root()
        assert root is not None
        assert verify_mmr_inclusion(root, leaf, peak_index, proof_bytes, other_peaks, peak)


def test_mmr_height() -> None:
    mmr = MerkleMountainRange()
    assert mmr.get_tree_height() == 0

    # Add leaves to create peaks of different heights
    leaves = [bytes32.random() for _ in range(5)]
    heights = [0, 1, 1, 2, 2]  # Correct expected peak heights after each append

    for leaf, expected_height in zip(leaves, heights):
        mmr.append(leaf)
        assert mmr.get_tree_height() == expected_height


@pytest.mark.anyio
async def test_mmr_block_inclusion_by_header_hash(default_1000_blocks: list[FullBlock]) -> None:
    mmr = MerkleMountainRange()
    header_hashes = [block.header_hash for block in default_1000_blocks]
    for hh in header_hashes:
        mmr.append(hh)
    # Test first, middle, last
    indices = [0, len(header_hashes) // 2, len(header_hashes) - 1]
    for idx in indices:
        hh = header_hashes[idx]
        proof = mmr.get_inclusion_proof_by_index(idx)
        assert proof is not None
        peak_index, proof_bytes, other_peaks, peak = proof
        root = mmr.compute_root()
        assert root is not None
        assert verify_mmr_inclusion(root, hh, peak_index, proof_bytes, other_peaks, peak)


@pytest.mark.anyio
async def test_mmr_benchmark_default_10000_blocks(default_10000_blocks: list[FullBlock]) -> None:
    mmr = MerkleMountainRange()
    header_hashes = [block.header_hash for block in default_10000_blocks]
    t0 = time.time()
    for hh in header_hashes:
        mmr.append(hh)

    t1 = time.time()
    append_time = t1 - t0
    sample_indices = random.sample(range(len(header_hashes)), 1000)
    proof_times = []
    for idx in sample_indices:
        hh = header_hashes[idx]
        t_start = time.time()
        proof = mmr.get_inclusion_proof_by_index(idx)
        t_end = time.time()
        proof_times.append(t_end - t_start)
        assert proof is not None
        peak_index, proof_bytes, other_peaks, peak = proof
        root = mmr.compute_root()
        assert root is not None
        assert verify_mmr_inclusion(root, hh, peak_index, proof_bytes, other_peaks, peak)

    avg_proof_time = sum(proof_times) / len(proof_times)
    logger.info(f"MMR append time for 10,000 blocks: {append_time:.4f} seconds")
    logger.info(f"Average proof time for 1,000 random blocks: {avg_proof_time:.6f} seconds")


# New tests for flat MMR structure
def test_flat_mmr_basic() -> None:
    """Test basic flat MMR operations"""
    mmr = MerkleMountainRange()
    assert mmr.leaf_count == 0
    assert len(mmr.nodes) == 0
    assert mmr.compute_root() is None

    # Add first leaf
    leaf1 = bytes32.random()
    mmr.append(leaf1)
    assert mmr.leaf_count == 1
    assert len(mmr.nodes) == 1  # Just the leaf
    assert mmr.compute_root() == leaf1  # Single leaf MMR root is the leaf itself

    # Add second leaf
    leaf2 = bytes32.random()
    mmr.append(leaf2)
    assert mmr.leaf_count == 2
    assert len(mmr.nodes) == 3  # 2 leaves + 1 parent
    # Root should be hash(leaf1 || leaf2)
    from chia.util.hash import std_hash

    expected_root = std_hash(leaf1 + leaf2)
    assert mmr.compute_root() == expected_root


def test_flat_mmr_peak_positions() -> None:
    assert get_peak_positions(0) == []
    assert get_peak_positions(1) == [0]
    assert get_peak_positions(3) == [2]
    assert get_peak_positions(4) == [3, 2]
    assert get_peak_positions(7) == [6]
    assert get_peak_positions(18) == [17, 14]
    assert get_peak_positions(19) == [18, 17, 14]


@pytest.mark.skip("Height calculation not needed - we store heights directly")
def test_flat_mmr_height_calculation() -> None:
    """Test height calculation from position"""
    assert get_height(0) == 0  # Leaf
    assert get_height(1) == 0  # Leaf
    assert get_height(2) == 1  # Parent of 0,1
    assert get_height(3) == 0  # Leaf
    assert get_height(4) == 0  # Leaf
    assert get_height(5) == 1  # Parent of 3,4
    assert get_height(6) == 2  # Parent of 2,5


def test_flat_mmr_copy() -> None:
    """Test MMR copy"""
    mmr = MerkleMountainRange()
    leaves = [bytes32.random() for _ in range(10)]
    for leaf in leaves:
        mmr.append(leaf)

    original_root = mmr.compute_root()

    # Copy and verify
    mmr2 = mmr.copy()
    assert mmr2.leaf_count == mmr.leaf_count
    assert len(mmr2.nodes) == len(mmr.nodes)
    assert mmr2.compute_root() == original_root

    # Modify copy shouldn't affect original
    mmr2.append(bytes32.random())
    assert mmr2.leaf_count != mmr.leaf_count
    assert mmr.compute_root() == original_root


def test_mmr_pop_single() -> None:
    """Test popping a single leaf from MMR"""
    mmr = MerkleMountainRange()
    leaf = bytes32.random()
    mmr.append(leaf)
    assert mmr.leaf_count == 1
    assert len(mmr.nodes) == 1

    # Pop the leaf
    mmr.pop()
    assert mmr.leaf_count == 0
    assert len(mmr.nodes) == 0
    assert mmr.compute_root() is None


def test_mmr_pop_multiple() -> None:
    """Test popping multiple leaves"""
    from chia.util.hash import std_hash

    mmr = MerkleMountainRange()
    leaf1 = bytes32.random()
    leaf2 = bytes32.random()
    leaf3 = bytes32.random()

    mmr.append(leaf1)
    mmr.append(leaf2)
    mmr.append(leaf3)

    assert mmr.leaf_count == 3
    # After 3 leaves: [leaf1, leaf2, parent(1,2), leaf3]
    assert len(mmr.nodes) == 4

    # Pop leaf3
    mmr.pop()
    assert mmr.leaf_count == 2
    # After pop: [leaf1, leaf2, parent(1,2)]
    assert len(mmr.nodes) == 3
    expected_root = std_hash(leaf1 + leaf2)
    assert mmr.compute_root() == expected_root

    # Pop leaf2
    mmr.pop()
    assert mmr.leaf_count == 1
    # After pop: [leaf1]
    assert len(mmr.nodes) == 1
    assert mmr.compute_root() == leaf1


def test_mmr_append_and_rewind() -> None:
    """Test maintaining two MMRs, appending extra blocks to one, then rewinding"""
    mmr1 = MerkleMountainRange()
    mmr2 = MerkleMountainRange()

    # Build up to a common point
    common_leaves = [bytes32.random() for _ in range(10)]
    for leaf in common_leaves:
        mmr1.append(leaf)
        mmr2.append(leaf)

    # Both should be identical
    assert mmr1.leaf_count == mmr2.leaf_count
    assert len(mmr1.nodes) == len(mmr2.nodes)
    assert mmr1.compute_root() == mmr2.compute_root()

    # Add extra blocks to mmr2
    extra_leaves = [bytes32.random() for _ in range(5)]
    for leaf in extra_leaves:
        mmr2.append(leaf)

    # Now they should differ
    assert mmr2.leaf_count == mmr1.leaf_count + 5
    assert mmr2.compute_root() != mmr1.compute_root()

    # Rewind mmr2 by popping 5 blocks
    for _ in range(5):
        mmr2.pop()

    # Now they should be identical again
    assert mmr1.leaf_count == mmr2.leaf_count
    assert len(mmr1.nodes) == len(mmr2.nodes)
    assert mmr1.compute_root() == mmr2.compute_root()
    # Verify all nodes are identical
    for i in range(len(mmr1.nodes)):
        assert mmr1.nodes[i] == mmr2.nodes[i]


def test_mmr_rewind_large_batch() -> None:
    """Test rewinding large batches of blocks"""
    mmr1 = MerkleMountainRange()
    mmr2 = MerkleMountainRange()

    # Build up baseline of 100 blocks
    baseline_leaves = [bytes32.random() for _ in range(100)]
    for leaf in baseline_leaves:
        mmr1.append(leaf)
        mmr2.append(leaf)

    baseline_root = mmr1.compute_root()

    # Add 50 extra blocks to mmr2
    extra_leaves = [bytes32.random() for _ in range(50)]
    for leaf in extra_leaves:
        mmr2.append(leaf)

    assert mmr2.leaf_count == 150
    assert mmr2.compute_root() != baseline_root

    # Rewind all 50 blocks
    for _ in range(50):
        mmr2.pop()

    # Verify we're back to baseline
    assert mmr2.leaf_count == 100
    assert mmr2.compute_root() == baseline_root
    assert mmr1.compute_root() == mmr2.compute_root()


def test_mmr_pop_nodes_calculation() -> None:
    """Test that pop correctly calculates nodes to remove"""
    mmr = MerkleMountainRange()

    # First append: adds 1 node (just the leaf)
    mmr.append(bytes32.random())
    assert len(mmr.nodes) == 1

    # Second append: adds 2 nodes (leaf + parent)
    mmr.append(bytes32.random())
    assert len(mmr.nodes) == 3

    # Third append: adds 1 node (just the leaf)
    mmr.append(bytes32.random())
    assert len(mmr.nodes) == 4

    # Fourth append: adds 3 nodes (leaf + parent + grandparent)
    mmr.append(bytes32.random())
    assert len(mmr.nodes) == 7

    # Pop should remove 3 nodes (leaf + parent + grandparent)
    mmr.pop()
    assert len(mmr.nodes) == 4
    assert mmr.leaf_count == 3

    # Pop should remove 1 node (just the leaf)
    mmr.pop()
    assert len(mmr.nodes) == 3
    assert mmr.leaf_count == 2

    # Pop should remove 2 nodes (leaf + parent)
    mmr.pop()
    assert len(mmr.nodes) == 1
    assert mmr.leaf_count == 1


def test_leaf_index_and_peak_positions() -> None:
    # 1 PEAK
    #         6
    #        / \
    #       2   5
    #      / \ / \
    #     0  1 3  4
    #

    mmr_1_peak = MerkleMountainRange()
    for i in range(4):
        mmr_1_peak.append(bytes32.random())

    assert leaf_index_to_pos(0) == 0
    assert leaf_index_to_pos(1) == 1
    assert leaf_index_to_pos(2) == 3
    assert leaf_index_to_pos(3) == 4
    peaks_1 = get_peak_positions(len(mmr_1_peak.nodes))
    assert peaks_1 == [6]

    # 2 PEAKS
    #       2 (peak)      3 (peak)
    #      / \
    #     0   1
    #
    mmr_2_peaks = MerkleMountainRange()
    for i in range(3):
        mmr_2_peaks.append(bytes32.random())
    assert leaf_index_to_pos(0) == 0
    assert leaf_index_to_pos(1) == 1
    assert leaf_index_to_pos(2) == 3
    peaks_2 = get_peak_positions(len(mmr_2_peaks.nodes))
    assert peaks_2 == [3, 2]

    # 3 PEAKS
    #        6 (peak)       9 (peak)     10 (peak)
    #       / \            / \
    #      2   5          7   8
    #     / \ / \
    #    0  1 3  4
    #
    mmr_3_peaks = MerkleMountainRange()
    for i in range(7):
        mmr_3_peaks.append(bytes32.random())
    assert leaf_index_to_pos(0) == 0
    assert leaf_index_to_pos(1) == 1
    assert leaf_index_to_pos(2) == 3
    assert leaf_index_to_pos(3) == 4
    assert leaf_index_to_pos(4) == 7
    assert leaf_index_to_pos(5) == 8
    assert leaf_index_to_pos(6) == 10
    peaks_3 = get_peak_positions(len(mmr_3_peaks.nodes))
    assert peaks_3 == [10, 9, 6]


def test_mmr_structure() -> None:
    # 1 PEAK: 4 leaves
    mmr_1 = MerkleMountainRange()
    leaves_1 = [bytes32.random() for _ in range(4)]
    for leaf in leaves_1:
        mmr_1.append(leaf)

    for i, leaf in enumerate(leaves_1):
        expected_pos = leaf_index_to_pos(i)
        assert mmr_1.nodes[expected_pos] == leaf

    # 2 PEAKS: 3 leaves
    mmr_2 = MerkleMountainRange()
    leaves_2 = [bytes32.random() for _ in range(3)]
    for leaf in leaves_2:
        mmr_2.append(leaf)

    for i, leaf in enumerate(leaves_2):
        expected_pos = leaf_index_to_pos(i)
        assert mmr_2.nodes[expected_pos] == leaf

    # 3 PEAKS: 7 leaves
    mmr_3 = MerkleMountainRange()
    leaves_3 = [bytes32.random() for _ in range(7)]
    for leaf in leaves_3:
        mmr_3.append(leaf)

    for i, leaf in enumerate(leaves_3):
        expected_pos = leaf_index_to_pos(i)
        assert mmr_3.nodes[expected_pos] == leaf

    # 4 PEAKS: 15 leaves
    mmr_4 = MerkleMountainRange()
    leaves_4 = [bytes32.random() for _ in range(15)]
    for leaf in leaves_4:
        mmr_4.append(leaf)

    for i, leaf in enumerate(leaves_4):
        expected_pos = leaf_index_to_pos(i)
        assert mmr_4.nodes[expected_pos] == leaf


def test_mmr_rollback_to_empty_when_already_empty() -> None:
    mmr = BlockchainMMRManager(DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    blocks = BlockCache({}, mmr_manager=mmr)
    assert mmr._last_height is None
    # check rollback to empty when already empty does not throw
    mmr.rollback_to_height(-1, blocks)
    assert mmr._last_height is None
    assert mmr._last_header_hash is None
    assert mmr.get_current_mmr_root() is None


def test_mmr_genesis_block_handling() -> None:
    mmr = BlockchainMMRManager(DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    blocks = BlockCache({}, mmr_manager=mmr)

    # Test genesis block: prev_header_hash equals genesis_challenge
    mmr_root = mmr.get_mmr_root_for_block(
        prev_header_hash=DEFAULT_CONSTANTS.GENESIS_CHALLENGE,  # Genesis case
        new_sp_index=0,
        starts_new_slot=True,
        blocks=blocks,
        fork_height=None,
    )

    assert mmr_root is None, "Genesis block should have empty MMR (None root)"

    # Verify the MMR state hasn't changed
    assert mmr._last_height is None
    assert mmr._last_header_hash is None
    assert mmr.get_current_mmr_root() is None


def test_mmr_aggregate_from_filtering() -> None:
    """Test that add_block_to_mmr respects aggregate_from and skips blocks before it."""
    from chia_rs.sized_ints import uint32

    from chia.consensus.blockchain_mmr import BlockchainMMRManager
    from chia.consensus.default_constants import DEFAULT_CONSTANTS

    # Create MMR with aggregate_from = 500 (simulating HARD_FORK2_HEIGHT)
    aggregate_from = uint32(500)
    mmr = BlockchainMMRManager(DEFAULT_CONSTANTS.GENESIS_CHALLENGE, aggregate_from=aggregate_from)

    # Try adding blocks before aggregate_from - should be skipped
    for height in range(500):
        block_hash = bytes32([height % 256] + [0] * 31)
        prev_hash = bytes32([(height - 1) % 256] + [0] * 31) if height > 0 else bytes32.zeros
        mmr.add_block_to_mmr(block_hash, prev_hash, uint32(height))

    # MMR should still be empty (no blocks added)
    assert mmr._last_height is None
    assert mmr._last_header_hash is None
    assert mmr.get_current_mmr_root() is None

    # Now add blocks from aggregate_from onwards - should be added
    for height in range(500, 505):
        block_hash = bytes32([height % 256] + [0] * 31)
        prev_hash = bytes32([(height - 1) % 256] + [0] * 31) if height > 500 else bytes32.zeros
        mmr.add_block_to_mmr(block_hash, prev_hash, uint32(height))

    # MMR should now contain 5 blocks (500-504)
    assert mmr._last_height == uint32(504)
    assert mmr.get_current_mmr_root() is not None

    # Verify the MMR has nodes for these 5 blocks
    assert len(mmr._mmr.nodes) > 0


def test_mmr_init_validation() -> None:
    mmr = MerkleMountainRange()
    for _ in range(10):
        mmr.append(bytes32.random())

    mmr2 = MerkleMountainRange(list(mmr.nodes), mmr.leaf_count)
    assert mmr2.leaf_count == mmr.leaf_count
    assert len(mmr2.nodes) == len(mmr.nodes)
    assert mmr2.compute_root() == mmr.compute_root()

    # Invalid: 3 leaves should have 4 nodes, not 5
    with pytest.raises(ValueError, match="Invalid MMR state"):
        MerkleMountainRange([bytes32.random() for _ in range(5)], uint32(3))

    # Invalid: 10 leaves should have 18 nodes (2*10 - popcount(10) = 20 - 2 = 18), not 10
    with pytest.raises(ValueError, match="Invalid MMR state"):
        MerkleMountainRange([bytes32.random() for _ in range(10)], uint32(10))


def test_verify_mmr_inclusion_malformed_proof() -> None:
    mmr_root = bytes32.random()
    leaf = bytes32.random()
    peak_index = uint32(0)
    other_peaks: list[bytes32] = []
    expected_peak = bytes32.random()

    # Proof too short - claims 1 sibling but only has header
    malformed_proof = (1).to_bytes(2, "big") + bytes([0])

    result = verify_mmr_inclusion(mmr_root, leaf, peak_index, malformed_proof, other_peaks, expected_peak)
    assert result is False, "Should reject proof with insufficient sibling data"


def test_mmr_rollback_below_aggregate_from() -> None:
    aggregate_from = uint32(500)
    mmr = BlockchainMMRManager(DEFAULT_CONSTANTS.GENESIS_CHALLENGE, aggregate_from=aggregate_from)

    block_records: dict[bytes32, BlockRecord] = {}
    for height in range(500, 505):
        block_hash = bytes32([height % 256] + [0] * 31)
        prev_hash = bytes32([(height - 1) % 256] + [0] * 31) if height > 500 else bytes32.zeros
        mmr.add_block_to_mmr(block_hash, prev_hash, uint32(height))

    blocks = BlockCache(block_records, mmr_manager=mmr)

    assert mmr._last_height == uint32(504)
    assert mmr.get_current_mmr_root() is not None

    # Rollback to height 99 (below aggregate_from) - should clear MMR
    mmr.rollback_to_height(99, blocks)

    assert mmr._last_height is None
    assert mmr._last_header_hash is None
    assert mmr.get_current_mmr_root() is None
