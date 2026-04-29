from __future__ import annotations

from hashlib import sha256

import pytest
from chia_rs import FullBlock, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.util.blockchain import create_blockchain
from chia.consensus.challenge_tree import (
    SlotChallengeData,
    build_challenge_merkle_tree,
    extract_slot_challenge_data,
)
from chia.consensus.get_block_challenge import get_block_challenge
from chia.simulator.block_tools import BlockTools, load_block_list
from chia.util.block_cache import BlockCache
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

    # Test merkle set with single slot
    # With compute_merkle_set_root, a single element hashes as: sha256(b"\1" + leaf)
    challenge_hash = bytes32([1] * 32)
    slot_data = [SlotChallengeData(challenge_hash=challenge_hash, block_count=uint32(5))]

    root = build_challenge_merkle_tree(slot_data)
    leaf = std_hash(challenge_hash + uint32(5).to_bytes(4, "big"))
    expected_root = bytes32(sha256(b"\1" + leaf).digest())
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

    # Test that merkle set is order-independent
    # (compute_merkle_set_root produces the same result regardless of order)
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

    # With merkle sets, different order should produce the SAME root
    assert root1 == root2


def test_extract_slot_challenge_data_covers_single_and_multi_slot_updates(bt: BlockTools) -> None:
    def find_slot_rollover_window(
        full_blocks: list[FullBlock],
    ) -> tuple[BlockCache, int | None, int | None]:
        _, _, block_records = load_block_list(full_blocks, bt.constants)
        cache = BlockCache(block_records, bt.constants.GENESIS_CHALLENGE)
        multi_height: int | None = None
        single_height: int | None = None

        for height in range(1, len(full_blocks)):
            block_record = cache.height_to_block_record(uint32(height))
            hashes = block_record.finished_challenge_slot_hashes
            if multi_height is None and block_record.first_in_sub_slot and hashes is not None and len(hashes) >= 2:
                multi_height = height
            elif (
                multi_height is not None and block_record.first_in_sub_slot and hashes is not None and len(hashes) == 1
            ):
                single_height = height
                break

        return cache, multi_height, single_height

    full_blocks = bt.get_consecutive_blocks(1, seed=b"challenge-tree-genesis")
    full_blocks = bt.get_consecutive_blocks(
        1,
        block_list_input=full_blocks,
        skip_slots=2,
        seed=b"challenge-tree-multi-slot",
    )
    full_blocks = bt.get_consecutive_blocks(
        2,
        block_list_input=full_blocks,
        seed=b"challenge-tree-after-multi",
    )
    full_blocks = bt.get_consecutive_blocks(
        1,
        block_list_input=full_blocks,
        skip_slots=1,
        seed=b"challenge-tree-single-slot",
    )
    full_blocks = bt.get_consecutive_blocks(
        2,
        block_list_input=full_blocks,
        seed=b"challenge-tree-after-single",
    )
    blocks, multi_slot_height, single_slot_height = find_slot_rollover_window(full_blocks)

    assert multi_slot_height is not None
    assert single_slot_height is not None

    start_height = uint32(multi_slot_height)
    end_height_int = min(len(full_blocks), single_slot_height + 3)
    end_height = uint32(end_height_int)
    expected_slot_data: list[SlotChallengeData] = []

    for block in full_blocks[multi_slot_height:end_height_int]:
        block_record = blocks.height_to_block_record(uint32(block.height))
        block_challenge = get_block_challenge(
            bt.constants,
            block,
            blocks,
            block.height == 0,
            block_record.overflow,
            False,
        )
        if not expected_slot_data or expected_slot_data[-1].challenge_hash != block_challenge:
            expected_slot_data.append(SlotChallengeData(block_challenge, uint32(1)))
        else:
            expected_slot_data[-1] = SlotChallengeData(block_challenge, uint32(expected_slot_data[-1].block_count + 1))

    assert extract_slot_challenge_data(blocks, start_height, end_height) == expected_slot_data


@pytest.mark.anyio
async def test_compute_challenge_merkle_root_sub_epoch_boundaries(
    bt: BlockTools, default_1000_blocks: list[FullBlock]
) -> None:
    async with create_blockchain(bt.constants, 2) as (blockchain, _):
        for block in default_1000_blocks:
            await _validate_and_add_block(blockchain, block)

        ses_start = uint32(0)
        for ses_height in blockchain.get_ses_heights():
            slot_data = extract_slot_challenge_data(blockchain, ses_start, ses_height)
            expected_slot_data: list[SlotChallengeData] = []
            for height in range(ses_start, ses_height):
                block_record = blockchain.height_to_block_record(uint32(height))
                header_block = await blockchain.get_header_block_by_height(
                    block_record.height, block_record.header_hash
                )
                assert header_block is not None
                block_challenge = get_block_challenge(
                    blockchain.constants,
                    header_block,
                    blockchain,
                    block_record.height == 0,
                    block_record.overflow,
                    False,
                )
                # Group consecutive blocks with same challenge into slots
                if len(expected_slot_data) == 0 or expected_slot_data[-1].challenge_hash != block_challenge:
                    # New consecutive run of blocks with this challenge
                    expected_slot_data.append(SlotChallengeData(challenge_hash=block_challenge, block_count=uint32(1)))
                else:
                    # Same challenge as previous block, increment count
                    expected_slot_data[-1] = SlotChallengeData(
                        challenge_hash=block_challenge,
                        block_count=uint32(expected_slot_data[-1].block_count + 1),
                    )
            # check slot data matches for each slot in the sub-epoch
            for idx, slot in enumerate(slot_data):
                assert slot == expected_slot_data[idx]

            ses_start = ses_height
