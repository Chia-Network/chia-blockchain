from typing import Dict, Optional, Union, List

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import is_overflow_sub_block
from src.consensus.deficit import calculate_deficit
from src.consensus.difficulty_adjustment import get_next_sub_slot_iters
from src.types.classgroup import ClassgroupElement
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeBlockInfo
from src.types.full_block import FullBlock
from src.consensus.sub_block_record import SubBlockRecord
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.ints import uint64, uint32
from src.consensus.make_sub_epoch_summary import make_sub_epoch_summary


def block_to_sub_block_record(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    required_iters: uint64,
    full_block: Optional[FullBlock],
    header_block: Optional[HeaderBlock],
):

    if full_block is None:
        assert header_block is not None
        block: Union[HeaderBlock, FullBlock] = header_block
    else:
        block = full_block
    if block.sub_block_height == 0:
        prev_sb: Optional[SubBlockRecord] = None
        sub_slot_iters: uint64 = uint64(constants.SUB_SLOT_ITERS_STARTING)
        height = 0
    else:
        prev_sb = sub_blocks[block.prev_header_hash]
        assert prev_sb is not None
        if prev_sb.is_block:
            height = prev_sb.height + 1
        else:
            height = prev_sb.height
        sub_slot_iters = get_next_sub_slot_iters(
            constants,
            sub_blocks,
            height_to_hash,
            prev_sb.prev_hash,
            prev_sb.sub_block_height,
            prev_sb.sub_slot_iters,
            prev_sb.deficit,
            len(block.finished_sub_slots) > 0,
            prev_sb.sp_total_iters(constants),
        )
    overflow = is_overflow_sub_block(constants, block.reward_chain_sub_block.signage_point_index)
    deficit = calculate_deficit(
        constants,
        block.sub_block_height,
        prev_sb,
        overflow,
        len(block.finished_sub_slots),
    )
    prev_block_hash = block.foliage_block.prev_block_hash if block.foliage_block is not None else None
    timestamp = block.foliage_block.timestamp if block.foliage_block is not None else None
    fees = block.transactions_info.fees if block.transactions_info is not None else None
    # reward_claims_incorporated = (
    #     block.transactions_info.reward_claims_incorporated if block.transactions_info is not None else None
    # )

    if len(block.finished_sub_slots) > 0:
        finished_challenge_slot_hashes: Optional[List[bytes32]] = [
            sub_slot.challenge_chain.get_hash() for sub_slot in block.finished_sub_slots
        ]
        finished_reward_slot_hashes: Optional[List[bytes32]] = [
            sub_slot.reward_chain.get_hash() for sub_slot in block.finished_sub_slots
        ]
        finished_infused_challenge_slot_hashes: Optional[List[bytes32]] = [
            sub_slot.infused_challenge_chain.get_hash()
            for sub_slot in block.finished_sub_slots
            if sub_slot.infused_challenge_chain is not None
        ]
    elif block.sub_block_height == 0:
        finished_challenge_slot_hashes = [constants.FIRST_CC_CHALLENGE]
        finished_reward_slot_hashes = [constants.FIRST_RC_CHALLENGE]
        finished_infused_challenge_slot_hashes = None
    else:
        finished_challenge_slot_hashes = None
        finished_reward_slot_hashes = None
        finished_infused_challenge_slot_hashes = None

    found_ses_hash: Optional[bytes32] = None
    ses: Optional[SubEpochSummary] = None
    if len(block.finished_sub_slots) > 0:
        for sub_slot in block.finished_sub_slots:
            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                found_ses_hash = sub_slot.challenge_chain.subepoch_summary_hash
    if found_ses_hash:
        assert prev_sb is not None
        assert len(block.finished_sub_slots) > 0
        ses = make_sub_epoch_summary(
            constants,
            sub_blocks,
            block.sub_block_height,
            sub_blocks[prev_sb.prev_hash],
            block.finished_sub_slots[0].challenge_chain.new_difficulty,
            block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
        )
        assert ses.get_hash() == found_ses_hash

    cbi = ChallengeBlockInfo(
        block.reward_chain_sub_block.proof_of_space,
        block.reward_chain_sub_block.challenge_chain_sp_vdf,
        block.reward_chain_sub_block.challenge_chain_sp_signature,
        block.reward_chain_sub_block.challenge_chain_ip_vdf,
    )

    if block.reward_chain_sub_block.infused_challenge_chain_ip_vdf is not None:
        icc_output: Optional[ClassgroupElement] = block.reward_chain_sub_block.infused_challenge_chain_ip_vdf.output
    else:
        icc_output = None
    return SubBlockRecord(
        block.header_hash,
        block.prev_header_hash,
        block.sub_block_height,
        uint32(height),
        block.weight,
        block.total_iters,
        block.reward_chain_sub_block.signage_point_index,
        block.reward_chain_sub_block.challenge_chain_ip_vdf.output,
        icc_output,
        block.reward_chain_sub_block.get_hash(),
        cbi.get_hash(),
        sub_slot_iters,
        block.foliage_sub_block.foliage_sub_block_data.pool_target.puzzle_hash,
        block.foliage_sub_block.foliage_sub_block_data.farmer_reward_puzzle_hash,
        required_iters,
        deficit,
        overflow,
        timestamp,
        prev_block_hash,
        fees,
        # reward_claims_incorporated,
        finished_challenge_slot_hashes,
        finished_infused_challenge_slot_hashes,
        finished_reward_slot_hashes,
        ses,
    )
