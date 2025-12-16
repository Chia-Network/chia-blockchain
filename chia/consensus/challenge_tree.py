"""
Challenge merkle tree utilities for sub-epoch challenge commitments.

This module provides functions to extract challenge data from blocks and build
deterministic merkle trees of slot-based challenge data for sub-epoch summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from chia_rs import ConsensusConstants
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.util.hash import std_hash
from chia.util.merkle_tree import MerkleTree

log = logging.getLogger(__name__)


@dataclass
class SlotChallengeData:
    """
    Represents challenge data for a single slot in a sub-epoch.
    Groups blocks by their slot challenge and tracks the count.
    """

    challenge_hash: bytes32  # The challenge hash for this slot
    block_count: uint32  # Number of blocks in this slot


def extract_slot_challenge_data(
    blocks: BlockRecordsProtocol,
    sub_epoch_start: uint32,
    sub_epoch_end: uint32,
) -> list[SlotChallengeData]:
    """
    Extract slot-based challenge data from blocks in a sub-epoch range.

    Groups blocks by their slot challenge and counts blocks per slot.
    Returns:
        List of SlotChallengeData objects, one per slot in the sub-epoch, ordered by first appearance
    """
    slot_data: list[SlotChallengeData] = []
    current_challenge: bytes32 | None = None
    prev_challenge: bytes32 | None = None
    curr = blocks.height_to_block_record(uint32(sub_epoch_start))
    reversed_challenge_hashes: list[bytes32] = []

    challenges_to_look_for = 1
    if curr.overflow:
        challenges_to_look_for = 2
    # find challenge for fitst block in sub-epoch
    while curr.height >= 0:
        if curr.first_in_sub_slot:
            assert curr.finished_challenge_slot_hashes is not None
            reversed_challenge_hashes += reversed(curr.finished_challenge_slot_hashes)
            if len(reversed_challenge_hashes) >= challenges_to_look_for:
                break
        if curr.height == 0:
            assert curr.finished_challenge_slot_hashes is not None
            assert len(curr.finished_challenge_slot_hashes) > 0
            break
    current_challenge = reversed_challenge_hashes[0]
    if challenges_to_look_for == 2:
        assert len(reversed_challenge_hashes) == 2
        prev_challenge = reversed_challenge_hashes[1]
    # go throgh all blocks in sub-epoch counting blocks per slot challenge
    for height in range(sub_epoch_start, sub_epoch_end + 1):
        try:
            block = blocks.height_to_block_record(uint32(height))

            # Update challenge state when we see a new slot
            if block.first_in_sub_slot:
                hashes = block.finished_challenge_slot_hashes
                assert hashes is not None  # hashes cant be None if first in sub slot
                if len(hashes) >= 2:
                    # Multiple slots finished, prev is second-to-last, current is last
                    prev_challenge = hashes[-2]
                    current_challenge = hashes[-1]
                else:
                    # Single slot finished
                    prev_challenge = current_challenge
                    current_challenge = hashes[-1]

            # Determine which challenge this block uses
            if not block.overflow:
                block_challenge = current_challenge
            else:
                assert prev_challenge is not None
                block_challenge = prev_challenge

            # Track slot data
            if not slot_data or slot_data[-1].challenge_hash != block_challenge:
                # New slot
                slot_data.append(SlotChallengeData(challenge_hash=block_challenge, block_count=uint32(1)))
            else:
                # Same slot, increment count
                slot_data[-1] = SlotChallengeData(
                    challenge_hash=block_challenge,
                    block_count=uint32(slot_data[-1].block_count + 1),
                )

        except Exception as e:
            log.warning(f"Could not access block at height {height} for challenge extraction: {e}")
            continue

    return slot_data


def build_challenge_merkle_tree(slot_data: list[SlotChallengeData]) -> bytes32:
    """
    Build deterministic merkle tree from slot challenge data.

    Each merkle leaf contains: hash(challenge_hash || block_count)
    The slot data is already in deterministic order (time-ordered by block height).
    """
    if not slot_data:
        log.warning("No slot data provided for challenge merkle tree")
        return bytes32.zeros

    # Create merkle tree leaves: hash(challenge_hash + block_count) for each slot
    merkle_leaves: list[bytes32] = []
    for slot in slot_data:
        # Create leaf: hash(challenge_hash || block_count)
        # block_count is serialized as 4-byte big-endian uint32
        leaf_data = slot.challenge_hash + slot.block_count.to_bytes(4, "big")
        leaf_hash = std_hash(leaf_data)
        merkle_leaves.append(leaf_hash)

    # Build merkle tree
    merkle_tree = MerkleTree(merkle_leaves)
    return merkle_tree.calculate_root()


def compute_challenge_merkle_root(
    constants: ConsensusConstants,
    blocks: BlockRecordsProtocol,
    blocks_included_height: uint32,
) -> bytes32:
    """
    Compute the merkle root of slot-based challenge data in the sub-epoch.
    This is the main entry point that combines extraction and tree building.

    Returns:
        bytes32: merkle root of slot challenge data in the sub-epoch
    """
    sub_epoch_end = blocks_included_height - 1

    if sub_epoch_end == 0:
        # First block is always the start of the first sub-epoch
        sub_epoch_start = uint32(0)
    else:
        # Walk backwards to find the previous sub-epoch summary
        curr = blocks.height_to_block_record(uint32(sub_epoch_end))
        while curr.height > 0 and curr.sub_epoch_summary_included is None:
            curr = blocks.block_record(curr.prev_hash)

        # The previous sub-epoch ended at curr.height -1
        if curr.sub_epoch_summary_included is not None:
            sub_epoch_start = uint32(curr.height)
        else:
            # We reached genesis without finding a summary, so this starts at genesis
            sub_epoch_start = uint32(0)

    # Extract slot challenge data from blocks
    slot_data = extract_slot_challenge_data(blocks, sub_epoch_start, uint32(sub_epoch_end))

    # Build and return merkle root
    return build_challenge_merkle_tree(slot_data)
