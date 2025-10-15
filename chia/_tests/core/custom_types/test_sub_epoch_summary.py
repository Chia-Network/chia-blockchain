from __future__ import annotations

from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64


def test_sub_epoch_summary_basic() -> None:
    # Create a basic SubEpochSummary
    ses = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        challenge_merkle_root=bytes32.zeros,  # placeholder
    )

    # Test basic properties
    assert ses.prev_subepoch_summary_hash == bytes32([5] * 32)
    assert ses.reward_chain_hash == bytes32([6] * 32)
    assert ses.num_blocks_overflow == uint8(7)
    assert ses.new_difficulty == uint64(8)
    assert ses.new_sub_slot_iters == uint64(9)
    assert ses.challenge_merkle_root == bytes32.zeros


def test_sub_epoch_summary_with_different_merkle_roots() -> None:
    # Test that different merkle roots create different instances
    ses1 = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        challenge_merkle_root=bytes32.zeros,  # different value
    )

    ses2 = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        challenge_merkle_root=bytes32([1] * 32),  # different value
    )

    # Different merkle roots should create different objects
    assert ses1.challenge_merkle_root != ses2.challenge_merkle_root


def test_sub_epoch_summary_optional_fields() -> None:
    # Test with None for optional fields
    ses = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([1] * 32),
        reward_chain_hash=bytes32([2] * 32),
        num_blocks_overflow=uint8(3),
        new_difficulty=None,
        new_sub_slot_iters=None,
        challenge_merkle_root=bytes32.zeros,  # placeholder
    )

    assert ses.new_difficulty is None
    assert ses.new_sub_slot_iters is None

    # Test with some optional fields set
    ses2 = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([1] * 32),
        reward_chain_hash=bytes32([2] * 32),
        num_blocks_overflow=uint8(3),
        new_difficulty=uint64(4),
        new_sub_slot_iters=None,
        challenge_merkle_root=bytes32.zeros,  # placeholder
    )

    assert ses2.new_difficulty == uint64(4)
    assert ses2.new_sub_slot_iters is None
