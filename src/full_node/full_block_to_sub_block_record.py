from src.types.challenge_slot import ChallengeBlockInfo
from src.types.full_block import FullBlock
from src.full_node.sub_block_record import SubBlockRecord
from src.util.ints import uint64, uint8


def full_block_to_sub_block_record(
    block: FullBlock, ips: uint64, required_iters: uint64, deficit: uint8
):
    prev_block_hash = (
        block.foliage_block.prev_block_hash if block.foliage_block is not None else None
    )
    timestamp = (
        block.foliage_block.timestamp if block.foliage_block is not None else None
    )
    if block.finished_slots is not None:
        finished_challenge_slot_hashes = [
            cs.get_hash() for cs, _, _ in block.finished_slots
        ]
        finished_reward_slot_hashes = [
            rs.get_hash() for _, rs, _ in block.finished_slots
        ]
    else:
        finished_challenge_slot_hashes = None
        finished_reward_slot_hashes = None

    sub_epoch_summary_included_hash = None
    if block.finished_slots is not None:
        for cs, _, _ in block.finished_slots:
            if cs.subepoch_summary_hash is not None:
                sub_epoch_summary_included_hash = cs.subepoch_summary_hash

    cbi = ChallengeBlockInfo(
        block.reward_chain_sub_block.proof_of_space,
        block.reward_chain_sub_block.challenge_chain_icp_vdf,
        block.reward_chain_sub_block.challenge_chain_icp_sig,
        block.reward_chain_sub_block.challenge_chain_ip_vdf,
    )

    return SubBlockRecord(
        block.header_hash,
        block.prev_header_hash,
        block.height,
        block.weight,
        block.total_iters,
        block.reward_chain_sub_block.challenge_chain_ip_vdf.output,
        block.reward_chain_sub_block.get_hash(),
        cbi.get_hash(),
        ips,
        block.foliage_sub_block.foliage_sub_block_data.pool_target.puzzle_hash,
        block.foliage_sub_block.foliage_sub_block_data.farmer_reward_puzzle_hash,
        required_iters,
        deficit,
        timestamp,
        prev_block_hash,
        finished_challenge_slot_hashes,
        finished_reward_slot_hashes,
        sub_epoch_summary_included_hash,
    )
