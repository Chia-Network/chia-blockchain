from __future__ import annotations

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.consensus.mmr import MerkleMountainRange
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary


def test_sub_epoch_summary_with_mmr() -> None:
    # Create empty MMRs
    header_mmr = MerkleMountainRange()
    vdf_mmr = MerkleMountainRange()

    # Add some test data
    header_mmr.append(bytes32([1] * 32))
    header_mmr.append(bytes32([2] * 32))

    vdf_mmr.append(bytes32([3] * 32))
    vdf_mmr.append(bytes32([4] * 32))

    # Create a SubEpochSummary
    ses = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        header_hash_mmr=header_mmr,
        vdf_mmr=vdf_mmr,
    )

    # Test that hash is deterministic
    hash1 = ses.get_hash()
    hash2 = ses.get_hash()
    assert hash1 == hash2

    # Test that different MMR contents produce different hashes
    header_mmr2 = MerkleMountainRange()
    header_mmr2.append(bytes32([10] * 32))

    ses2 = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        header_hash_mmr=header_mmr2,
        vdf_mmr=vdf_mmr,
    )

    assert ses.get_hash() != ses2.get_hash()


def test_sub_epoch_summary_mmr_proofs() -> None:
    # Create MMRs with test data
    header_mmr = MerkleMountainRange()
    vdf_mmr = MerkleMountainRange()

    test_header = bytes32([1] * 32)
    test_vdf = bytes32([2] * 32)

    header_mmr.append(test_header)
    vdf_mmr.append(test_vdf)

    # Create SubEpochSummary
    ses = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([3] * 32),
        reward_chain_hash=bytes32([4] * 32),
        num_blocks_overflow=uint8(5),
        new_difficulty=uint64(6),
        new_sub_slot_iters=uint64(7),
        header_hash_mmr=header_mmr,
        vdf_mmr=vdf_mmr,
    )

    # Test header hash inclusion proof
    header_proof = ses.header_hash_mmr.get_inclusion_proof(test_header)
    assert header_proof is not None
    peak_index, proof_bytes, other_peaks = header_proof
    assert ses.header_hash_mmr.verify_inclusion(test_header, peak_index, proof_bytes, other_peaks)

    # Test VDF inclusion proof
    vdf_proof = ses.vdf_mmr.get_inclusion_proof(test_vdf)
    assert vdf_proof is not None
    peak_index, proof_bytes, other_peaks = vdf_proof
    assert ses.vdf_mmr.verify_inclusion(test_vdf, peak_index, proof_bytes, other_peaks)

    # Test non-inclusion proofs
    non_included_header = bytes32([8] * 32)
    non_included_vdf = bytes32([9] * 32)

    assert ses.header_hash_mmr.get_inclusion_proof(non_included_header) is None
    assert ses.vdf_mmr.get_inclusion_proof(non_included_vdf) is None


def test_sub_epoch_summary_optional_fields() -> None:
    # Create empty MMRs
    header_mmr = MerkleMountainRange()
    vdf_mmr = MerkleMountainRange()

    # Test with None for optional fields
    ses = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([1] * 32),
        reward_chain_hash=bytes32([2] * 32),
        num_blocks_overflow=uint8(3),
        new_difficulty=None,
        new_sub_slot_iters=None,
        header_hash_mmr=header_mmr,
        vdf_mmr=vdf_mmr,
    )

    # Hash should still be deterministic
    hash1 = ses.get_hash()
    hash2 = ses.get_hash()
    assert hash1 == hash2

    # Test with some optional fields set
    ses2 = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([1] * 32),
        reward_chain_hash=bytes32([2] * 32),
        num_blocks_overflow=uint8(3),
        new_difficulty=uint64(4),
        new_sub_slot_iters=None,
        header_hash_mmr=header_mmr,
        vdf_mmr=vdf_mmr,
    )

    # Different optional fields should produce different hashes
    assert ses.get_hash() != ses2.get_hash()
