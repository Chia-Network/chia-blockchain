"""
Challenge merkle tree utilities for sub-epoch challenge commitments.

This module provides functions to extract challenge data from blocks and build
deterministic merkle trees of slot-based challenge data for sub-epoch summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from chia_rs import BlockRecord, ConsensusConstants
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.util.hash import std_hash
from chia.wallet.util.merkle_tree import MerkleTree

log = logging.getLogger(__name__)


@dataclass
class SlotChallengeData:
    """
    Represents challenge data for a single slot in a sub-epoch.
    Groups blocks by their slot challenge and tracks the count.
    """

    challenge_hash: bytes32  # The challenge hash for this slot
    block_count: uint32  # Number of blocks in this slot


def get_challenge_for_block_record(
    constants: ConsensusConstants,
    blocks: BlockRecordsProtocol,
    block: BlockRecord,
) -> bytes32:
    """
    Get the challenge that a block was built against by walking back to find
    the finished_challenge_slot_hashes.

    This is similar to get_block_challenge but works with BlockRecord instead of FullBlock.
    Overflow blocks belong to the previous slot, so they use the second-to-last challenge.

    Args:
        constants: consensus constants
        blocks: blockchain interface to access block records
        block: the block record to get challenge for

    Returns:
        bytes32: the challenge hash this block was built against
    """
    # Genesis block uses genesis challenge
    if block.height == 0:
        return constants.GENESIS_CHALLENGE

    # Determine how many challenges to look for
    # Overflow blocks use second-to-last challenge (belong to previous slot)
    # Normal blocks use last challenge
    challenges_to_look_for = 2 if block.overflow else 1

    # Collect challenge hashes by walking back through blocks
    reversed_challenge_hashes: list[bytes32] = []
    curr = block

    while len(reversed_challenge_hashes) < challenges_to_look_for:
        if curr.first_in_sub_slot:
            # This block has finished_challenge_slot_hashes
            if curr.finished_challenge_slot_hashes is not None:
                reversed_challenge_hashes += reversed(curr.finished_challenge_slot_hashes)
                if len(reversed_challenge_hashes) >= challenges_to_look_for:
                    break

        if curr.height == 0:
            # Reached genesis
            if curr.finished_challenge_slot_hashes is not None and len(curr.finished_challenge_slot_hashes) > 0:
                reversed_challenge_hashes += reversed(curr.finished_challenge_slot_hashes)
            break

        # Move to previous block
        curr = blocks.block_record(curr.prev_hash)

    # Return the appropriate challenge
    if len(reversed_challenge_hashes) >= challenges_to_look_for:
        return reversed_challenge_hashes[challenges_to_look_for - 1]
    elif len(reversed_challenge_hashes) > 0:
        # Fallback to last available challenge
        return reversed_challenge_hashes[-1]
    else:
        # Final fallback to genesis challenge
        log.warning(f"Could not find challenge for block at height {block.height}")
        return constants.GENESIS_CHALLENGE


def extract_slot_challenge_data(
    constants: ConsensusConstants,
    blocks: BlockRecordsProtocol,
    sub_epoch_start: uint32,
    sub_epoch_end: uint32,
) -> list[SlotChallengeData]:
    """
    Extract slot-based challenge data from blocks in a sub-epoch range.

    Groups blocks by their slot challenge (finished_challenge_slot_hashes)
    and counts how many blocks are in each slot. Walks back through the blockchain
    to find the actual challenge each block was built against.

    Overflow blocks are counted in the slot their challenge belongs to, even if they
    appear later in the blockchain (after the slot has moved forward).

    Args:
        constants: consensus constants
        blocks: blockchain interface to access block records
        sub_epoch_start: first block height in sub-epoch
        sub_epoch_end: last block height in sub-epoch

    Returns:
        List of SlotChallengeData objects, one per slot in the sub-epoch, ordered by first appearance
    """
    # Use dict to accumulate counts per slot (handles overflow blocks appearing later)
    slot_counts: dict[bytes32, int] = {}
    slot_order: list[bytes32] = []  # Track order of first appearance

    for height in range(sub_epoch_start, sub_epoch_end + 1):
        try:
            block = blocks.height_to_block_record(uint32(height))

            # Determine slot challenge - walk back to find the actual challenge this block was built against
            # Overflow blocks will return the challenge from the previous slot
            slot_challenge = get_challenge_for_block_record(constants, blocks, block)

            # Track first appearance of this slot challenge
            if slot_challenge not in slot_counts:
                slot_order.append(slot_challenge)
                slot_counts[slot_challenge] = 0

            # Increment count for this slot
            slot_counts[slot_challenge] += 1

        except Exception as e:
            log.warning(f"Could not access block at height {height} for challenge extraction: {e}")
            continue

    # Convert to list of SlotChallengeData in order of first appearance
    slot_data: list[SlotChallengeData] = []
    for challenge_hash in slot_order:
        slot_data.append(
            SlotChallengeData(
                challenge_hash=challenge_hash,
                block_count=uint32(slot_counts[challenge_hash]),
            )
        )

    return slot_data


def build_challenge_merkle_tree(slot_data: list[SlotChallengeData]) -> bytes32:
    """
    Build deterministic merkle tree from slot challenge data.

    Each merkle leaf contains: hash(challenge_hash || block_count)
    The slot data is already in deterministic order (time-ordered by block height).

    Args:
        slot_data: List of SlotChallengeData objects in block height order

    Returns:
        bytes32: merkle root of the challenge tree, or zeros if empty
    """
    # Handle empty sub-epoch case
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

    Args:
        constants: consensus constants
        blocks: blockchain interface to access block records
        blocks_included_height: height where the sub-epoch summary will be included

    Returns:
        bytes32: merkle root of slot challenge data in the sub-epoch
    """
    # Calculate the range of blocks in this sub-epoch
    sub_epoch_start = ((blocks_included_height - 1) // constants.SUB_EPOCH_BLOCKS) * constants.SUB_EPOCH_BLOCKS
    sub_epoch_end = blocks_included_height - 1  # Last block in sub-epoch

    # Extract slot challenge data from blocks
    slot_data = extract_slot_challenge_data(constants, blocks, uint32(sub_epoch_start), uint32(sub_epoch_end))

    # Build and return merkle root
    return build_challenge_merkle_tree(slot_data)
