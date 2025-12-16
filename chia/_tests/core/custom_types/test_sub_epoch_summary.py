from __future__ import annotations

from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia.consensus.challenge_tree import (
    SlotChallengeData,
    build_challenge_merkle_tree,
)
from chia.util.casts import int_to_bytes
from chia.util.hash import std_hash


def test_sub_epoch_summary_basic() -> None:
    # Create a basic SubEpochSummary
    ses = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        challenge_merkle_root=None,
    )

    # Test basic properties
    assert ses.prev_subepoch_summary_hash == bytes32([5] * 32)
    assert ses.reward_chain_hash == bytes32([6] * 32)
    assert ses.num_blocks_overflow == uint8(7)
    assert ses.new_difficulty == uint64(8)
    assert ses.new_sub_slot_iters == uint64(9)
    assert ses.challenge_merkle_root is None


def test_sub_epoch_summary_with_different_merkle_roots() -> None:
    # Test that different merkle roots create different instances
    ses1 = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        challenge_merkle_root=bytes32([1] * 32),  # different value
    )

    ses2 = SubEpochSummary(
        prev_subepoch_summary_hash=bytes32([5] * 32),
        reward_chain_hash=bytes32([6] * 32),
        num_blocks_overflow=uint8(7),
        new_difficulty=uint64(8),
        new_sub_slot_iters=uint64(9),
        challenge_merkle_root=bytes32([2] * 32),  # different value
    )

    # Different merkle roots should create different objects
    assert ses1.get_hash() != ses2.get_hash()


def test_build_challenge_merkle_tree() -> None:
    # Test that empty slot data returns zeros
    root = build_challenge_merkle_tree([])
    assert root == bytes32.zeros
    #  Test merkle tree with single slot
    challenge_hash = bytes32([1] * 32)
    slot_data = [SlotChallengeData(challenge_hash=challenge_hash, block_count=uint32(5))]

    root = build_challenge_merkle_tree(slot_data)
    leaf = std_hash(challenge_hash + uint32(5).to_bytes(4, "big"))
    expected_root = std_hash(int_to_bytes(1) + leaf)
    assert root == expected_root


def test_build_challenge_merkle_tree_multiple_slots() -> None:
    """Test merkle tree with multiple slots."""
    slot_data = [
        SlotChallengeData(challenge_hash=bytes32([1] * 32), block_count=uint32(3)),
        SlotChallengeData(challenge_hash=bytes32([2] * 32), block_count=uint32(7)),
        SlotChallengeData(challenge_hash=bytes32([3] * 32), block_count=uint32(2)),
    ]

    root = build_challenge_merkle_tree(slot_data)

    # Should produce a non-zero root
    assert root != bytes32.zeros

    # Building the same tree again should produce the same root (deterministic)
    root2 = build_challenge_merkle_tree(slot_data)
    assert root == root2

    # Different slot data should produce different root
    different_slot_data = [
        SlotChallengeData(challenge_hash=bytes32([1] * 32), block_count=uint32(3)),
        SlotChallengeData(challenge_hash=bytes32([2] * 32), block_count=uint32(8)),  # Different count
        SlotChallengeData(challenge_hash=bytes32([3] * 32), block_count=uint32(2)),
    ]
    different_root = build_challenge_merkle_tree(different_slot_data)
    assert root != different_root
    #  slot order affects the merkle root
    slot_data_1 = [
        SlotChallengeData(challenge_hash=bytes32([1] * 32), block_count=uint32(3)),
        SlotChallengeData(challenge_hash=bytes32([2] * 32), block_count=uint32(7)),
    ]

    slot_data_2 = [
        SlotChallengeData(challenge_hash=bytes32([2] * 32), block_count=uint32(7)),
        SlotChallengeData(challenge_hash=bytes32([1] * 32), block_count=uint32(3)),
    ]

    root1 = build_challenge_merkle_tree(slot_data_1)
    root2 = build_challenge_merkle_tree(slot_data_2)

    # Different order should produce different root
    assert root1 != root2
