from typing import Optional

from src.consensus.pot_iterations import calculate_iterations_quality
from src.types.full_block import FullBlock
from src.full_node.sub_block_record import SubBlockRecord
from src.consensus.constants import ConsensusConstants
from src.types.sized_bytes import bytes32
from src.util.ints import uint64


def full_block_to_sub_block_record(constants: ConsensusConstants, block: FullBlock, ips: uint64, difficulty: uint64):
    prev_block_hash = block.foliage_block.prev_block_hash if block.foliage_block is not None else None
    timestamp = block.foliage_block.timestamp if block.foliage_block is not None else None

    q_str: Optional[bytes32] = block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
        constants.NUMBER_ZERO_BITS_CHALLENGE_SIG
    )
    # TODO: remove redundant verification of PoSpace
    required_iters: uint64 = calculate_iterations_quality(
        q_str,
        block.reward_chain_sub_block.proof_of_space.size,
        difficulty,
    )

    if block.finished_slots is not None:
        finished_challenge_slot_hashes = [cs.get_hash() for cs, _, _ in block.finished_slots]
        finished_reward_slot_hashes = [rs.get_hash() for _, rs, _ in block.finished_slots]
        deficit = block.finished_slots[-1][1].deficit
        previous_slot_non_overflow_infusions = block.finished_slots[-1][1].made_non_overflow_infusions
    else:
        finished_challenge_slot_hashes = None
        finished_reward_slot_hashes = None
        deficit = None
        previous_slot_non_overflow_infusions = None

    sub_epoch_summary_included_hash = None
    if block.finished_slots is not None:
        for cs, _, _ in block.finished_slots:
            if cs.subepoch_summary_hash is not None:
                sub_epoch_summary_included_hash = cs.subepoch_summary_hash

    return SubBlockRecord(
        block.header_hash,
        block.prev_header_hash,
        block.height,
        block.weight,
        block.total_iters,
        block.reward_chain_sub_block.challenge_chain_ip_vdf.output,
        block.reward_chain_sub_block.get_hash(),
        ips,
        block.foliage_sub_block.signed_data.pool_target.puzzle_hash,
        block.foliage_sub_block.signed_data.farmer_reward_puzzle_hash,
        required_iters,
        block.challenge_chain_icp_proof is not None,
        timestamp,
        prev_block_hash,
        finished_challenge_slot_hashes,
        finished_reward_slot_hashes,
        deficit,
        previous_slot_non_overflow_infusions,
        sub_epoch_summary_included_hash,
    )
