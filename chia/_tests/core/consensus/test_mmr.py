import pytest
from chia.consensus.mmr import MerkleMountainRange, MMRPeak
from chia_rs.sized_bytes import bytes32
import os
from chia_rs import FullBlock
from typing import List
import time
import random
import logging

logger = logging.getLogger(__name__)


def random_bytes32() -> bytes32:
    return bytes32(os.urandom(32))


def test_empty_mmr_root() -> None:
    mmr = MerkleMountainRange()
    assert mmr.get_root() == bytes32([0] * 32)
    assert mmr.get_inclusion_proof(random_bytes32()) is None


def test_single_leaf() -> None:
    mmr = MerkleMountainRange()
    leaf = random_bytes32()
    mmr.append(leaf)
    root = mmr.get_root()
    proof = mmr.get_inclusion_proof(leaf)
    assert proof is not None
    peak_index, proof_bytes, other_peaks = proof
    assert mmr.verify_inclusion(leaf, peak_index, proof_bytes, other_peaks)


def test_multiple_leaves() -> None:
    mmr = MerkleMountainRange()
    leaves = [random_bytes32() for _ in range(10)]
    for leaf in leaves:
        mmr.append(leaf)
    root = mmr.get_root()
    for leaf in leaves:
        proof = mmr.get_inclusion_proof(leaf)
        assert proof is not None
        peak_index, proof_bytes, other_peaks = proof
        assert mmr.verify_inclusion(leaf, peak_index, proof_bytes, other_peaks)
    # Root should be stable
    mmr2 = MerkleMountainRange()
    for leaf in leaves:
        mmr2.append(leaf)
    assert mmr2.get_root() == root


def test_duplicate_leaves() -> None:
    mmr = MerkleMountainRange()
    leaf = random_bytes32()
    for _ in range(3):
        mmr.append(leaf)
    # All should be provable
    for i in range(3):
        proof = mmr.get_inclusion_proof(leaf)
        assert proof is not None
        peak_index, proof_bytes, other_peaks = proof
        assert mmr.verify_inclusion(leaf, peak_index, proof_bytes, other_peaks)


def test_serialize_deserialize() -> None:
    mmr = MerkleMountainRange()
    leaves = [random_bytes32() for _ in range(5)]
    for leaf in leaves:
        mmr.append(leaf)
    data = mmr.serialize()
    mmr2 = MerkleMountainRange.deserialize(data)
    assert mmr2.get_root() == mmr.get_root()
    for leaf in leaves:
        proof = mmr2.get_inclusion_proof(leaf)
        assert proof is not None
        peak_index, proof_bytes, other_peaks = proof
        assert mmr2.verify_inclusion(leaf, peak_index, proof_bytes, other_peaks)


def test_mmr_peak_validation() -> None:
    # Test height validation
    with pytest.raises(ValueError, match="Height cannot be negative"):
        MMRPeak(-1, [random_bytes32()])
    
    # Test empty elements validation
    with pytest.raises(ValueError, match="Elements list cannot be empty"):
        MMRPeak(0, [])
    
    # Test get_num_leaves
    peak = MMRPeak(1, [random_bytes32(), random_bytes32()])
    assert peak.get_num_leaves() == 2


def test_mmr_input_validation() -> None:
    mmr = MerkleMountainRange()
    
    # Test invalid leaf type
    with pytest.raises(ValueError, match="Leaf must be bytes32"):
        mmr.append(b"not a bytes32")  # type: ignore
    
    # Test invalid peak index
    leaf = random_bytes32()
    mmr.append(leaf)
    proof = mmr.get_inclusion_proof(leaf)
    assert proof is not None
    peak_index, proof_bytes, other_peaks = proof
    
    with pytest.raises(ValueError, match="Invalid peak index"):
        mmr.verify_inclusion(leaf, -1, proof_bytes, other_peaks)
    
    with pytest.raises(ValueError, match="Invalid peak index"):
        mmr.verify_inclusion(leaf, 1, proof_bytes, other_peaks)


def test_mmr_height() -> None:
    mmr = MerkleMountainRange()
    assert mmr.get_height() == 0
    
    # Add leaves to create peaks of different heights
    leaves = [random_bytes32() for _ in range(5)]
    heights = [0, 1, 2, 0, 1]  # Expected peak heights after each append
    
    for leaf, expected_height in zip(leaves, heights):
        mmr.append(leaf)
        assert mmr.get_height() == expected_height


def test_batch_verification() -> None:
    mmr = MerkleMountainRange()
    leaves = [random_bytes32() for _ in range(10)]
    for leaf in leaves:
        mmr.append(leaf)
    
    # Collect proofs for all leaves
    proofs = []
    for leaf in leaves:
        proof = mmr.get_inclusion_proof(leaf)
        assert proof is not None
        proofs.append(proof)
    
    # Test successful batch verification
    assert mmr.verify_batch_inclusion(leaves, proofs)
    
    # Test mismatched lengths
    with pytest.raises(ValueError, match="Number of leaves must match number of proofs"):
        mmr.verify_batch_inclusion(leaves[:-1], proofs)
    
    # Test failed verification with invalid proof
    invalid_proofs = proofs.copy()
    invalid_proofs[0] = (0, b"invalid proof", [])
    assert not mmr.verify_batch_inclusion(leaves, invalid_proofs)


def test_serialization_validation() -> None:
    # Test invalid data type
    with pytest.raises(ValueError, match="Invalid serialized data format"):
        MerkleMountainRange.deserialize([])  # type: ignore
    
    # Test missing required fields
    with pytest.raises(ValueError, match="Missing required fields in serialized data"):
        MerkleMountainRange.deserialize({"peaks": []})  # type: ignore
    
    with pytest.raises(ValueError, match="Missing required fields in serialized data"):
        MerkleMountainRange.deserialize({"size": 0})  # type: ignore


@pytest.mark.anyio
def test_mmr_block_inclusion_by_header_hash(default_1000_blocks: List[FullBlock]) -> None:
    mmr = MerkleMountainRange()
    header_hashes = [block.header_hash for block in default_1000_blocks]
    for hh in header_hashes:
        mmr.append(hh)
    # Test first, middle, last
    indices = [0, len(header_hashes) // 2, len(header_hashes) - 1]
    for idx in indices:
        hh = header_hashes[idx]
        proof = mmr.get_inclusion_proof(hh)
        assert proof is not None
        peak_index, proof_bytes, other_peaks = proof
        assert mmr.verify_inclusion(hh, peak_index, proof_bytes, other_peaks)
    # Negative test: random hashes not in the chain
    for _ in range(5):
        fake_hash = random_bytes32()
        while fake_hash in header_hashes:
            fake_hash = random_bytes32()
        proof = mmr.get_inclusion_proof(fake_hash)
        assert proof is None


def test_mmr_non_inclusion_small() -> None:
    mmr = MerkleMountainRange()
    leaves = [random_bytes32() for _ in range(5)]
    for leaf in leaves:
        mmr.append(leaf)
    for _ in range(1000):
        fake = random_bytes32()
        while fake in leaves:
            fake = random_bytes32()
        proof = mmr.get_inclusion_proof(fake)
        assert proof is None


@pytest.mark.anyio
def test_mmr_benchmark_default_10000_blocks(default_10000_blocks: List[FullBlock]) -> None:
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
        proof = mmr.get_inclusion_proof(hh)
        t_end = time.time()
        proof_times.append(t_end - t_start)
        assert proof is not None
        peak_index, proof_bytes, other_peaks = proof
        assert mmr.verify_inclusion(hh, peak_index, proof_bytes, other_peaks)
    avg_proof_time = sum(proof_times) / len(proof_times)
    logger.info(f"MMR append time for 10,000 blocks: {append_time:.4f} seconds")
    logger.info(f"Average proof time for 1,000 random blocks: {avg_proof_time:.6f} seconds") 