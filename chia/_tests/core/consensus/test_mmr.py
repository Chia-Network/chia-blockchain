from __future__ import annotations

import logging
import random
import time

import pytest
from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32

from chia.consensus.mmr import MerkleMountainRange, get_height, get_peak_positions, verify_mmr_inclusion

logger = logging.getLogger(__name__)


def test_empty_mmr_root() -> None:
    mmr = MerkleMountainRange()
    assert mmr.get_root() is None  # Empty MMR returns None
    # Note: get_inclusion_proof not yet implemented
    # assert mmr.get_inclusion_proof(random_bytes32()) is None


def test_single_leaf() -> None:
    mmr = MerkleMountainRange()
    leaf = bytes32.random()
    mmr.append(leaf)
    root = mmr.get_root()
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
    root = mmr.get_root()
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
    root2 = mmr2.get_root()
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
        root = mmr.get_root()
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
        root = mmr.get_root()
        assert root is not None
        assert verify_mmr_inclusion(root, hh, peak_index, proof_bytes, other_peaks, peak)


@pytest.mark.anyio
async def test_mmr_benchmark_default_10000_blocks(default_10000_blocks: list[FullBlock]) -> None:
    mmr = MerkleMountainRange()
    header_hashes = [block.header_hash for block in default_10000_blocks]
    t0 = time.time()
    for idx, hh in enumerate(header_hashes):
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
        root = mmr.get_root()
        assert root is not None
        assert verify_mmr_inclusion(root, hh, peak_index, proof_bytes, other_peaks, peak)

    avg_proof_time = sum(proof_times) / len(proof_times)
    logger.info(f"MMR append time for 10,000 blocks: {append_time:.4f} seconds")
    logger.info(f"Average proof time for 1,000 random blocks: {avg_proof_time:.6f} seconds")


# New tests for flat MMR structure
def test_flat_mmr_basic() -> None:
    """Test basic flat MMR operations"""
    mmr = MerkleMountainRange()
    assert mmr.size == 0
    assert len(mmr.nodes) == 0
    assert mmr.get_root() is None

    # Add first leaf
    leaf1 = bytes32.random()
    mmr.append(leaf1)
    assert mmr.size == 1
    assert len(mmr.nodes) == 1  # Just the leaf
    assert mmr.get_root() == leaf1  # Single leaf MMR root is the leaf itself

    # Add second leaf
    leaf2 = bytes32.random()
    mmr.append(leaf2)
    assert mmr.size == 2
    assert len(mmr.nodes) == 3  # 2 leaves + 1 parent
    # Root should be hash(leaf1 || leaf2)
    from chia.util.hash import std_hash

    expected_root = std_hash(leaf1 + leaf2)
    assert mmr.get_root() == expected_root


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

    original_root = mmr.get_root()

    # Copy and verify
    mmr2 = mmr.copy()
    assert mmr2.size == mmr.size
    assert len(mmr2.nodes) == len(mmr.nodes)
    assert mmr2.get_root() == original_root

    # Modify copy shouldn't affect original
    mmr2.append(bytes32.random())
    assert mmr2.size != mmr.size
    assert mmr.get_root() == original_root


def test_mmr_pop_single() -> None:
    """Test popping a single leaf from MMR"""
    mmr = MerkleMountainRange()
    leaf = bytes32.random()
    mmr.append(leaf)
    assert mmr.size == 1
    assert len(mmr.nodes) == 1

    # Pop the leaf
    mmr.pop()
    assert mmr.size == 0
    assert len(mmr.nodes) == 0
    assert mmr.get_root() is None


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

    assert mmr.size == 3
    # After 3 leaves: [leaf1, leaf2, parent(1,2), leaf3]
    assert len(mmr.nodes) == 4

    # Pop leaf3
    mmr.pop()
    assert mmr.size == 2
    # After pop: [leaf1, leaf2, parent(1,2)]
    assert len(mmr.nodes) == 3
    expected_root = std_hash(leaf1 + leaf2)
    assert mmr.get_root() == expected_root

    # Pop leaf2
    mmr.pop()
    assert mmr.size == 1
    # After pop: [leaf1]
    assert len(mmr.nodes) == 1
    assert mmr.get_root() == leaf1


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
    assert mmr1.size == mmr2.size
    assert len(mmr1.nodes) == len(mmr2.nodes)
    assert mmr1.get_root() == mmr2.get_root()

    # Add extra blocks to mmr2
    extra_leaves = [bytes32.random() for _ in range(5)]
    for leaf in extra_leaves:
        mmr2.append(leaf)

    # Now they should differ
    assert mmr2.size == mmr1.size + 5
    assert mmr2.get_root() != mmr1.get_root()

    # Rewind mmr2 by popping 5 blocks
    for _ in range(5):
        mmr2.pop()

    # Now they should be identical again
    assert mmr1.size == mmr2.size
    assert len(mmr1.nodes) == len(mmr2.nodes)
    assert mmr1.get_root() == mmr2.get_root()
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

    baseline_root = mmr1.get_root()

    # Add 50 extra blocks to mmr2
    extra_leaves = [bytes32.random() for _ in range(50)]
    for leaf in extra_leaves:
        mmr2.append(leaf)

    assert mmr2.size == 150
    assert mmr2.get_root() != baseline_root

    # Rewind all 50 blocks
    for _ in range(50):
        mmr2.pop()

    # Verify we're back to baseline
    assert mmr2.size == 100
    assert mmr2.get_root() == baseline_root
    assert mmr1.get_root() == mmr2.get_root()


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
    assert mmr.size == 3

    # Pop should remove 1 node (just the leaf)
    mmr.pop()
    assert len(mmr.nodes) == 3
    assert mmr.size == 2

    # Pop should remove 2 nodes (leaf + parent)
    mmr.pop()
    assert len(mmr.nodes) == 1
    assert mmr.size == 1
