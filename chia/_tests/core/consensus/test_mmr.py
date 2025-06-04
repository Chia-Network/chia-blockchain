from __future__ import annotations

import logging
import os
import random
import time
from typing import List

import pytest
from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32, bytes100
from chia_rs.sized_ints import uint64

from chia.consensus.mmr import MerkleMountainRange, MMRPeak, VDFProofMmr
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import VDFInfo

logger = logging.getLogger(__name__)


def random_bytes32() -> bytes32:
    return bytes32(os.urandom(32))


def test_empty_mmr_root() -> None:
    mmr = MerkleMountainRange.create()
    assert mmr.get_root() == bytes32([0] * 32)
    assert mmr.get_inclusion_proof(random_bytes32()) is None


def test_single_leaf() -> None:
    mmr = MerkleMountainRange.create()
    leaf = random_bytes32()
    mmr.append(leaf)
    root = mmr.get_root()
    proof = mmr.get_inclusion_proof(leaf)
    assert proof is not None
    peak_index, proof_bytes, other_peaks = proof
    assert mmr.verify_inclusion(leaf, peak_index, proof_bytes, other_peaks)


def test_multiple_leaves() -> None:
    mmr = MerkleMountainRange.create()
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
    mmr2 = MerkleMountainRange.create()
    for leaf in leaves:
        mmr2.append(leaf)
    assert mmr2.get_root() == root


def test_duplicate_leaves() -> None:
    mmr = MerkleMountainRange.create()
    leaf = random_bytes32()
    for _ in range(3):
        mmr.append(leaf)
    # All should be provable
    for i in range(3):
        proof = mmr.get_inclusion_proof(leaf)
        assert proof is not None
        peak_index, proof_bytes, other_peaks = proof
        assert mmr.verify_inclusion(leaf, peak_index, proof_bytes, other_peaks)


def test_mmr_peak_validation() -> None:
    # Test height validation
    with pytest.raises(ValueError, match="Height cannot be negative"):
        MMRPeak.create(-1, [random_bytes32()])

    # Test empty elements validation
    with pytest.raises(ValueError, match="Elements list cannot be empty"):
        MMRPeak.create(uint64(0), [])

    # Test get_num_leaves
    peak = MMRPeak.create(uint64(1), [random_bytes32(), random_bytes32()])
    assert peak.get_num_leaves() == 2


def test_mmr_input_validation() -> None:
    mmr = MerkleMountainRange.create()

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
    mmr = MerkleMountainRange.create()
    assert mmr.get_height() == 0

    # Add leaves to create peaks of different heights
    leaves = [random_bytes32() for _ in range(5)]
    heights = [0, 1, 1, 2, 2]  # Correct expected peak heights after each append

    for leaf, expected_height in zip(leaves, heights):
        mmr.append(leaf)
        assert mmr.get_height() == expected_height


def test_batch_verification() -> None:
    mmr = MerkleMountainRange.create()
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


@pytest.mark.anyio
async def test_mmr_block_inclusion_by_header_hash(default_1000_blocks: List[FullBlock]) -> None:
    mmr = MerkleMountainRange.create()
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
    mmr = MerkleMountainRange.create()
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
async def test_mmr_benchmark_default_10000_blocks(default_10000_blocks: List[FullBlock]) -> None:
    mmr = MerkleMountainRange.create()
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


def create_test_vdf_proof(challenge: bytes32, iters: int, output_data: bytes100, element_data: bytes100) -> VDFProofMmr:
    """Helper function to create a test VDFProofMmr instance"""
    vdf_output = ClassgroupElement(output_data)
    vdf_info = VDFInfo(challenge, uint64(iters), vdf_output)
    element = ClassgroupElement(element_data)
    return VDFProofMmr(vdf_info, element)


def test_vdf_mmr_encoding() -> None:
    """Test encoding VDF proofs in MMR"""
    mmr = MerkleMountainRange.create()

    # Create test data
    challenge1 = bytes32(b"1" * 32)
    challenge2 = bytes32(b"2" * 32)
    output_data1 = bytes100(b"3" * 100)
    output_data2 = bytes100(b"4" * 100)
    element_data1 = bytes100(b"5" * 100)
    element_data2 = bytes100(b"6" * 100)

    # Create and add proofs to MMR
    proof1 = create_test_vdf_proof(challenge1, 1000, output_data1, element_data1)
    proof2 = create_test_vdf_proof(challenge2, 2000, output_data2, element_data2)

    mmr.append(proof1.get_hash())
    mmr.append(proof2.get_hash())

    # Test inclusion proofs
    for proof in [proof1, proof2]:
        proof_hash = proof.get_hash()
        inclusion_proof = mmr.get_inclusion_proof(proof_hash)
        assert inclusion_proof is not None, "Should get inclusion proof for added VDF proof"
        peak_index, proof_bytes, other_peaks = inclusion_proof
        assert mmr.verify_inclusion(proof_hash, peak_index, proof_bytes, other_peaks), (
            "Should verify included VDF proof"
        )

    # Test non-inclusion
    different_proof = create_test_vdf_proof(bytes32(b"7" * 32), 3000, bytes100(b"8" * 100), bytes100(b"9" * 100))
    assert mmr.get_inclusion_proof(different_proof.get_hash()) is None, (
        "Should not get inclusion proof for non-added VDF proof"
    )


def test_vdf_mmr_hash_consistency() -> None:
    """Test that VDF proof hashes are consistent and unique"""
    # Create two proofs with same data
    challenge = bytes32(b"1" * 32)
    output_data = bytes100(b"2" * 100)
    element_data = bytes100(b"3" * 100)

    proof1 = create_test_vdf_proof(challenge, 1000, output_data, element_data)
    proof2 = create_test_vdf_proof(challenge, 1000, output_data, element_data)

    # Same data should produce same hash
    assert proof1.get_hash() == proof2.get_hash(), "Same VDF proof data should produce same hash"

    # Different iterations should produce different hash
    proof3 = create_test_vdf_proof(challenge, 2000, output_data, element_data)
    assert proof1.get_hash() != proof3.get_hash(), "Different iterations should produce different hash"

    # Different challenge should produce different hash
    proof4 = create_test_vdf_proof(bytes32(b"4" * 32), 1000, output_data, element_data)
    assert proof1.get_hash() != proof4.get_hash(), "Different challenge should produce different hash"


def test_vdf_mmr_batch_operations() -> None:
    """Test batch operations with VDF proofs in MMR"""
    mmr = MerkleMountainRange.create()
    proofs = []

    # Create and add multiple proofs
    for i in range(5):
        challenge = bytes32([i] * 32)
        output_data = bytes100([i + 1] * 100)
        element_data = bytes100([i + 2] * 100)
        proof = create_test_vdf_proof(challenge, i * 1000, output_data, element_data)
        proofs.append(proof)
        mmr.append(proof.get_hash())

    # Get all inclusion proofs
    inclusion_proofs = []
    for proof in proofs:
        inclusion_proof = mmr.get_inclusion_proof(proof.get_hash())
        assert inclusion_proof is not None
        inclusion_proofs.append(inclusion_proof)

    # Verify batch inclusion
    hashes = [proof.get_hash() for proof in proofs]
    assert mmr.verify_batch_inclusion(hashes, inclusion_proofs), "Batch verification should succeed"

    # Verify batch inclusion fails with wrong proof
    wrong_proofs = inclusion_proofs.copy()
    wrong_proofs[0] = (0, b"wrong proof", [])
    assert not mmr.verify_batch_inclusion(hashes, wrong_proofs), "Batch verification should fail with wrong proof"


def test_vdf_mmr_proving_and_non_inclusion() -> None:
    """Test comprehensive proving scenarios including non-inclusion cases"""
    mmr = MerkleMountainRange.create()

    # Create a set of test proofs
    proofs = []
    for i in range(3):
        challenge = bytes32([i] * 32)
        output_data = bytes100([i + 1] * 100)
        element_data = bytes100([i + 2] * 100)
        proof = create_test_vdf_proof(challenge, i * 1000, output_data, element_data)
        proofs.append(proof)
        mmr.append(proof.get_hash())

    root = mmr.get_root()

    # Test 1: Verify all added proofs are provable
    for proof in proofs:
        inclusion_proof = mmr.get_inclusion_proof(proof.get_hash())
        assert inclusion_proof is not None, "Should get inclusion proof for added VDF proof"
        peak_index, proof_bytes, other_peaks = inclusion_proof

        # Verify using the MMR's verify_inclusion method
        assert mmr.verify_inclusion(proof.get_hash(), peak_index, proof_bytes, other_peaks), (
            "Added proof should be verifiable"
        )

        # Try verifying with wrong peak index
        with pytest.raises(ValueError, match="Invalid peak index"):
            mmr.verify_inclusion(proof.get_hash(), peak_index + len(mmr.peaks), proof_bytes, other_peaks)

        # Try verifying with wrong proof bytes
        wrong_proof_bytes = b"wrong proof bytes"
        assert not mmr.verify_inclusion(proof.get_hash(), peak_index, wrong_proof_bytes, other_peaks), (
            "Should fail with wrong proof bytes"
        )

        # Try verifying with wrong peaks
        wrong_peaks = [random_bytes32()]
        assert not mmr.verify_inclusion(proof.get_hash(), peak_index, proof_bytes, wrong_peaks), (
            "Should fail with wrong peaks"
        )

    # Test 2: Verify non-included proofs cannot be proven
    for i in range(3):
        # Create proofs with different parameters
        non_included_proofs = [
            # Different challenge
            create_test_vdf_proof(
                bytes32([100 + i] * 32),  # Different challenge
                i * 1000,
                bytes100([i + 1] * 100),
                bytes100([i + 2] * 100),
            ),
            # Different iterations
            create_test_vdf_proof(
                bytes32([i] * 32),
                (i + 100) * 1000,  # Different iterations
                bytes100([i + 1] * 100),
                bytes100([i + 2] * 100),
            ),
            # Different output data
            create_test_vdf_proof(
                bytes32([i] * 32),
                i * 1000,
                bytes100([100 + i] * 100),  # Different output
                bytes100([i + 2] * 100),
            ),
            # Different element data
            create_test_vdf_proof(
                bytes32([i] * 32),
                i * 1000,
                bytes100([i + 1] * 100),
                bytes100([100 + i] * 100),  # Different element
            ),
        ]

        for non_included_proof in non_included_proofs:
            # Verify we can't get an inclusion proof
            inclusion_proof = mmr.get_inclusion_proof(non_included_proof.get_hash())
            assert inclusion_proof is None, "Should not get inclusion proof for non-included VDF proof"

            # Even if we try to forge a proof using valid proof components
            for valid_proof in proofs:
                valid_inclusion = mmr.get_inclusion_proof(valid_proof.get_hash())
                assert valid_inclusion is not None
                peak_index, proof_bytes, other_peaks = valid_inclusion

                # Try to use the valid proof components for the non-included proof
                assert not mmr.verify_inclusion(non_included_proof.get_hash(), peak_index, proof_bytes, other_peaks), (
                    "Should not verify non-included proof even with valid proof components"
                )

    # Test 3: Verify completely random data cannot be proven
    for _ in range(10):
        random_hash = random_bytes32()
        inclusion_proof = mmr.get_inclusion_proof(random_hash)
        assert inclusion_proof is None, "Should not get inclusion proof for random hash"

        # Try with some valid proof components
        valid_inclusion = mmr.get_inclusion_proof(proofs[0].get_hash())
        assert valid_inclusion is not None
        peak_index, proof_bytes, other_peaks = valid_inclusion

        assert not mmr.verify_inclusion(random_hash, peak_index, proof_bytes, other_peaks), (
            "Should not verify random hash even with valid proof components"
        )

    # Test 4: Verify modified proofs cannot be proven
    for proof in proofs:
        original_hash = proof.get_hash()
        inclusion_proof = mmr.get_inclusion_proof(original_hash)
        assert inclusion_proof is not None
        peak_index, proof_bytes, other_peaks = inclusion_proof

        # Try to verify a slightly modified hash
        modified_bytes = bytearray(original_hash)
        modified_bytes[0] = (modified_bytes[0] + 1) % 256  # Modify one byte
        modified_hash = bytes32(modified_bytes)

        assert not mmr.verify_inclusion(modified_hash, peak_index, proof_bytes, other_peaks), (
            "Should not verify modified hash even with valid proof components"
        )
