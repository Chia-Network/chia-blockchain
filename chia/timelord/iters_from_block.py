from __future__ import annotations

from typing import Union

from chia_rs import ConsensusConstants, RewardChainBlock, RewardChainBlockUnfinished
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_sp_iters,
    validate_pospace_and_get_required_iters,
)


def iters_from_block(
    constants: ConsensusConstants,
    reward_chain_block: Union[RewardChainBlock, RewardChainBlockUnfinished],
    sub_slot_iters: uint64,
    difficulty: uint64,
    height: uint32,
    prev_transaction_block_height: uint32,
) -> tuple[uint64, uint64]:
    if reward_chain_block.challenge_chain_sp_vdf is None:
        assert reward_chain_block.signage_point_index == 0
        cc_sp: bytes32 = reward_chain_block.pos_ss_cc_challenge_hash
    else:
        cc_sp = reward_chain_block.challenge_chain_sp_vdf.output.get_hash()

    required_iters = validate_pospace_and_get_required_iters(
        constants,
        reward_chain_block.proof_of_space,
        reward_chain_block.pos_ss_cc_challenge_hash,
        cc_sp,
        height,
        difficulty,
        sub_slot_iters,
        prev_transaction_block_height,
    )
    assert required_iters is not None

    return (
        calculate_sp_iters(constants, sub_slot_iters, reward_chain_block.signage_point_index),
        calculate_ip_iters(
            constants,
            sub_slot_iters,
            reward_chain_block.signage_point_index,
            required_iters,
        ),
    )
