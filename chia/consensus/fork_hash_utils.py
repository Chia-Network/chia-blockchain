from __future__ import annotations

from chia_rs import RewardChainBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


def get_reward_chain_block_hash_with_fork_validation(
    reward_chain_block: RewardChainBlock,
    fork_height: uint32,
) -> bytes32:
    """
    Compute reward chain block hash with fork-aware validation.

    Pre-fork (height < fork_height): asserts header_mmr_root is zeros, hashes as old format.
    Post-fork (height >= fork_height): asserts header_mmr_root is NOT zeros, hashes as new format.
    """
    if reward_chain_block.height < fork_height:
        # pre-fork: must have zeros
        assert (
            reward_chain_block.header_mmr_root == bytes32([0] * 32)
        ), f"pre-fork block at height {reward_chain_block.height} must have zeroed header_mmr_root"
        # hash as old format (excluding header_mmr_root field)
        return bytes32(reward_chain_block.to_old().get_hash())
    else:
        # post-fork: must NOT have zeros
        assert (
            reward_chain_block.header_mmr_root != bytes32([0] * 32)
        ), f"post-fork block at height {reward_chain_block.height} must have non-zero header_mmr_root"
        # hash as new format (including header_mmr_root field)
        return bytes32(reward_chain_block.get_hash())
