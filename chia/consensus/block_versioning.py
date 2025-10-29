"""
Block versioning utilities for HARD_FORK2_HEIGHT.

Handles serialization/deserialization of versioned block structures:
- RewardChainBlock / RewardChainBlockOld
- SubEpochSummary / SubEpochSummaryOld
- FullBlock / FullBlockOld
- HeaderBlock / HeaderBlockOld

Internal representation uses new types (with header_mmr_root and challenge_merkle_root).
Serialization format depends on block height relative to HARD_FORK2_HEIGHT.
"""

from __future__ import annotations

from chia_rs import (
    ConsensusConstants,
    FullBlock,
    HeaderBlock,
    RewardChainBlock,
    SubEpochSummary,
)
from chia_rs.sized_ints import uint32


def should_use_v2_format(height: uint32, constants: ConsensusConstants) -> bool:
    """Determine if we should use V2 format for a block at given height."""
    return height >= constants.HARD_FORK2_HEIGHT


# FullBlock serialization
def full_block_to_bytes(block: FullBlock, constants: ConsensusConstants) -> bytes:
    """Serialize FullBlock in old or new format based on height."""
    if should_use_v2_format(block.reward_chain_block.height, constants):
        return bytes(block)
    else:
        # Pre-fork: downgrade to old and serialize
        # Use to_old() which validates that new fields are zeros
        return bytes(block.to_old())


def full_block_from_bytes(data: bytes) -> FullBlock:
    """Deserialize FullBlock from bytes, handling old and new formats."""
    # Try new format first (will work for post-fork blocks)
    try:
        return FullBlock.from_bytes(data)
    except Exception:
        # Fall back to old format and upgrade
        from chia_rs import FullBlockOld

        old_block = FullBlockOld.from_bytes(data)
        return old_block.to_new()


# HeaderBlock serialization
def header_block_to_bytes(block: HeaderBlock, constants: ConsensusConstants) -> bytes:
    """Serialize HeaderBlock in old or new format based on height."""
    if should_use_v2_format(block.reward_chain_block.height, constants):
        return bytes(block)
    else:
        return bytes(block.to_old())


def header_block_from_bytes(data: bytes) -> HeaderBlock:
    """Deserialize HeaderBlock from bytes, handling old and new formats."""
    try:
        return HeaderBlock.from_bytes(data)
    except Exception:
        from chia_rs import HeaderBlockOld

        old_block = HeaderBlockOld.from_bytes(data)
        return old_block.to_new()


# RewardChainBlock serialization
def reward_chain_block_to_bytes(block: RewardChainBlock, height: uint32, constants: ConsensusConstants) -> bytes:
    """Serialize RewardChainBlock in old or new format based on height."""
    if should_use_v2_format(height, constants):
        return bytes(block)
    else:
        return bytes(block.to_old())


def reward_chain_block_from_bytes(data: bytes) -> RewardChainBlock:
    """Deserialize RewardChainBlock from bytes, handling old and new formats."""
    try:
        return RewardChainBlock.from_bytes(data)
    except Exception:
        from chia_rs import RewardChainBlockOld

        old_block = RewardChainBlockOld.from_bytes(data)
        return old_block.to_new()


# SubEpochSummary serialization
def sub_epoch_summary_to_bytes(summary: SubEpochSummary, height: uint32, constants: ConsensusConstants) -> bytes:
    """Serialize SubEpochSummary in old or new format based on height."""
    if should_use_v2_format(height, constants):
        return bytes(summary)
    else:
        return bytes(summary.to_old())


def sub_epoch_summary_from_bytes(data: bytes) -> SubEpochSummary:
    """Deserialize SubEpochSummary from bytes, handling old and new formats."""
    try:
        return SubEpochSummary.from_bytes(data)
    except Exception:
        from chia_rs import SubEpochSummaryOld

        old_summary = SubEpochSummaryOld.from_bytes(data)
        return old_summary.to_new()


# Protocol message serialization helpers
def serialize_respond_block(block: FullBlock, constants: ConsensusConstants) -> bytes:
    """
    Manually serialize RespondBlock protocol message with versioned block serialization.

    Returns raw bytes that can be passed to make_msg().
    """

    # Serialize the block using versioned serialization
    block_bytes = full_block_to_bytes(block, constants)

    # Manually construct RespondBlock message: just the block bytes
    # (RespondBlock is a simple wrapper with single field)
    return block_bytes


def serialize_respond_blocks(
    start_height: uint32, end_height: uint32, blocks: list[FullBlock], constants: ConsensusConstants
) -> bytes:
    """
    Manually serialize RespondBlocks protocol message with versioned block serialization.

    Returns raw bytes that can be passed to make_msg().
    """

    # Serialize each block using versioned serialization
    blocks_bytes = b"".join(full_block_to_bytes(block, constants) for block in blocks)

    # Manually construct RespondBlocks message
    # Format: start_height (4 bytes) + end_height (4 bytes) + blocks count (4 bytes) + blocks
    result = b""
    result += bytes(start_height)
    result += bytes(end_height)
    result += len(blocks).to_bytes(4, "big")  # list length prefix
    result += blocks_bytes

    return result


def serialize_respond_header_blocks(blocks: list[HeaderBlock], constants: ConsensusConstants) -> bytes:
    """
    Manually serialize RespondHeaderBlocks protocol message with versioned block serialization.

    Returns raw bytes that can be passed to make_msg().
    """
    # Serialize each header block using versioned serialization
    blocks_bytes = b"".join(header_block_to_bytes(block, constants) for block in blocks)

    # Manually construct RespondHeaderBlocks message
    # Format: blocks count (4 bytes) + blocks
    result = b""
    result += len(blocks).to_bytes(4, "big")  # list length prefix
    result += blocks_bytes

    return result
