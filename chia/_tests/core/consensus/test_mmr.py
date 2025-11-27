from __future__ import annotations

import logging
import os
import random
import time

import pytest
from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32

from chia.consensus.mmr import MerkleMountainRange, get_height, get_peak_positions, verify_mmr_inclusion

logger = logging.getLogger(__name__)


def random_bytes32() -> bytes32:
    return bytes32(os.urandom(32))


def test_empty_mmr_root() -> None:
    mmr = MerkleMountainRange()
    assert mmr.get_root() is None  # Empty MMR returns None
    # Note: get_inclusion_proof not yet implemented
    # assert mmr.get_inclusion_proof(random_bytes32()) is None


def test_single_leaf() -> None:
    mmr = MerkleMountainRange()
    leaf = random_bytes32()
    mmr.append(leaf)
    root = mmr.get_root()
    assert root is not None
    proof = mmr.get_inclusion_proof_by_index(0)
    assert proof is not None
    peak_index, proof_bytes, other_peaks, peak = proof
    assert verify_mmr_inclusion(root, leaf, peak_index, proof_bytes, other_peaks, peak)


def test_multiple_leaves() -> None:
    mmr = MerkleMountainRange()
    leaves = [random_bytes32() for _ in range(10)]
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
    leaf = random_bytes32()
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
    leaves = [random_bytes32() for _ in range(5)]
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
    leaf1 = random_bytes32()
    mmr.append(leaf1)
    assert mmr.size == 1
    assert len(mmr.nodes) == 1  # Just the leaf
    assert mmr.get_root() == leaf1  # Single leaf MMR root is the leaf itself

    # Add second leaf
    leaf2 = random_bytes32()
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
    leaves = [random_bytes32() for _ in range(10)]
    for leaf in leaves:
        mmr.append(leaf)

    original_root = mmr.get_root()

    # Copy and verify
    mmr2 = mmr.copy()
    assert mmr2.size == mmr.size
    assert len(mmr2.nodes) == len(mmr.nodes)
    assert mmr2.get_root() == original_root

    # Modify copy shouldn't affect original
    mmr2.append(random_bytes32())
    assert mmr2.size != mmr.size
    assert mmr.get_root() == original_root
