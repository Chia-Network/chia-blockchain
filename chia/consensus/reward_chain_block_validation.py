from __future__ import annotations

import logging
from collections.abc import Sequence

from chia_rs import BlockRecord, ChallengeBlockInfo, ConsensusConstants, RewardChainBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64, uint128

from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.util.errors import Err, ValidationError

log = logging.getLogger(__name__)


def get_same_signage_point_records(
    blocks: BlockRecordsProtocol,
    prev_b: BlockRecord | None,
    signage_point_index: uint8,
    starts_new_sub_slot: bool,
) -> list[BlockRecord]:
    if prev_b is None or starts_new_sub_slot:
        return []

    same_sp_records: list[BlockRecord] = []
    curr = prev_b
    while curr.signage_point_index == signage_point_index:
        same_sp_records.append(curr)
        if curr.first_in_sub_slot:
            break
        curr = blocks.block_record(curr.prev_hash)
    return same_sp_records


def validate_reward_chain_block_transition(
    constants: ConsensusConstants,
    reward_chain_block: RewardChainBlock,
    prev_header_hash: bytes32,
    prev_b: BlockRecord | None,
    genesis_block: bool,
    same_sp_records: Sequence[BlockRecord],
    expected_difficulty: uint64,
) -> ValidationError | None:
    """Validate a reward-chain block against its parent and current signage-point history."""

    if genesis_block:
        assert prev_b is None
        if reward_chain_block.height != 0:
            return ValidationError(Err.INVALID_HEIGHT)
        if reward_chain_block.weight != uint128(constants.DIFFICULTY_STARTING):
            log.error(f"INVALID WEIGHT: {reward_chain_block.get_hash()} {prev_b} {expected_difficulty}")
            return ValidationError(Err.INVALID_WEIGHT)
        if prev_header_hash != constants.GENESIS_CHALLENGE:
            return ValidationError(Err.INVALID_PREV_BLOCK_HASH)
        return None

    assert prev_b is not None
    if reward_chain_block.height != prev_b.height + 1:
        return ValidationError(Err.INVALID_HEIGHT)
    if reward_chain_block.weight != prev_b.weight + expected_difficulty:
        log.error(f"INVALID WEIGHT: {reward_chain_block.get_hash()} {prev_b} {expected_difficulty}")
        return ValidationError(Err.INVALID_WEIGHT)

    challenge_block_info_hash = ChallengeBlockInfo(
        reward_chain_block.proof_of_space,
        reward_chain_block.challenge_chain_sp_vdf,
        reward_chain_block.challenge_chain_sp_signature,
        reward_chain_block.challenge_chain_ip_vdf,
    ).get_hash()
    for block_record in same_sp_records:
        if block_record.challenge_block_info_hash == challenge_block_info_hash:
            return ValidationError(Err.INVALID_REWARD_CHAIN_HASH)

    return None
