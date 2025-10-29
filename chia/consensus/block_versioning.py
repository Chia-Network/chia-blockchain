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
