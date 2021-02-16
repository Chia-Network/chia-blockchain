from typing import Optional, Union

from src.consensus.blockchain_interface import BlockchainInterface
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_sp_iters,
    is_overflow_block,
)
from src.consensus.deficit import calculate_deficit
from src.consensus.difficulty_adjustment import (
    can_finish_sub_and_full_epoch,
    get_next_difficulty,
    get_next_sub_slot_iters,
)
from src.consensus.block_record import BlockRecord
from src.types.full_block import FullBlock
from src.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.ints import uint32, uint64, uint8, uint128

import logging

log = logging.getLogger(__name__)


def make_sub_epoch_summary(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    blocks_included_height: uint32,
    prev_prev_block: BlockRecord,
    new_difficulty: Optional[uint64],
    new_sub_slot_iters: Optional[uint64],
) -> SubEpochSummary:
    """
    Creates a sub-epoch-summary object, assuming that the first block in the new sub-epoch is at height
    "blocks_included_height". Prev_prev_b is the second to last block in the previous sub-epoch. On a new epoch,
    new_difficulty and new_sub_slot_iters are also added.

    Args:
        constants: consensus constants being used for this chain
        blocks: dictionary from header hash to SBR of all included SBR
        blocks_included_height: block height in which the SES will be included
        prev_prev_block: second to last block in epoch
        new_difficulty: difficulty in new epoch
        new_sub_slot_iters: sub slot iters in new epoch
    """
    assert prev_prev_block.height == blocks_included_height - 2
    # If first sub_epoch. Adds MAX_SUB_SLOT_BLOCKS because blocks_included_height might be behind
    if (blocks_included_height + constants.MAX_SUB_SLOT_BLOCKS) // constants.SUB_EPOCH_BLOCKS == 1:
        return SubEpochSummary(
            constants.GENESIS_CHALLENGE,
            constants.GENESIS_CHALLENGE,
            uint8(0),
            None,
            None,
        )
    curr: BlockRecord = prev_prev_block
    while curr.sub_epoch_summary_included is None:
        curr = blocks.block_record(curr.prev_hash)
    assert curr is not None
    assert curr.finished_reward_slot_hashes is not None
    prev_ses = curr.sub_epoch_summary_included.get_hash()
    return SubEpochSummary(
        prev_ses,
        curr.finished_reward_slot_hashes[-1],
        uint8(curr.height % constants.SUB_EPOCH_BLOCKS),
        new_difficulty,
        new_sub_slot_iters,
    )


def next_sub_epoch_summary(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    required_iters: uint64,
    block: Union[UnfinishedBlock, FullBlock],
    can_finish_soon: bool = False,
) -> Optional[SubEpochSummary]:
    """
    Returns the sub-epoch summary that can be included in the block after block. If it should include one. Block
    must be eligible to be the last block in the epoch. If not, returns None. Assumes that there is a new slot
    ending after block.

    Args:
        constants: consensus constants being used for this chain
        blocks: interface to cached SBR
        required_iters: required iters of the proof of space in block
        block: the (potentially) last block in the new epoch
        can_finish_soon: this is useful when sending SES to timelords. We might not be able to finish it, but we will
            soon (within MAX_SUB_SLOT_BLOCKS)

    Returns:
        object: the new sub-epoch summary
    """
    signage_point_index = block.reward_chain_block.signage_point_index
    prev_b: Optional[BlockRecord] = blocks.try_block_record(block.prev_header_hash)
    if prev_b is None or prev_b.height == 0:
        return None

    if len(block.finished_sub_slots) > 0 and block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
        # We just included a sub-epoch summary
        return None

    assert prev_b is not None
    # This is the ssi of the current block
    sub_slot_iters = get_next_sub_slot_iters(
        constants,
        blocks,
        prev_b.prev_hash,
        prev_b.height,
        prev_b.sub_slot_iters,
        prev_b.deficit,
        len(block.finished_sub_slots) > 0,
        prev_b.sp_total_iters(constants),
    )
    overflow = is_overflow_block(constants, signage_point_index)
    deficit = calculate_deficit(
        constants,
        uint32(prev_b.height + 1),
        prev_b,
        overflow,
        len(block.finished_sub_slots),
    )
    can_finish_se, can_finish_epoch = can_finish_sub_and_full_epoch(
        constants,
        uint32(prev_b.height + 1),
        deficit,
        blocks,
        prev_b.header_hash if prev_b is not None else None,
        can_finish_soon,
    )

    # can't finish se, no summary
    if not can_finish_se:
        return None

    next_difficulty = None
    next_sub_slot_iters = None

    # if can finish epoch, new difficulty and ssi
    if can_finish_epoch:
        sp_iters = calculate_sp_iters(constants, sub_slot_iters, signage_point_index)
        ip_iters = calculate_ip_iters(constants, sub_slot_iters, signage_point_index, required_iters)
        next_difficulty = get_next_difficulty(
            constants,
            blocks,
            block.prev_header_hash,
            uint32(prev_b.height + 1),
            uint64(prev_b.weight - blocks.block_record(prev_b.prev_hash).weight),
            deficit,
            True,
            uint128(block.total_iters - ip_iters + sp_iters - (sub_slot_iters if overflow else 0)),
            True,
        )
        next_sub_slot_iters = get_next_sub_slot_iters(
            constants,
            blocks,
            block.prev_header_hash,
            uint32(prev_b.height + 1),
            sub_slot_iters,
            deficit,
            True,
            uint128(block.total_iters - ip_iters + sp_iters - (sub_slot_iters if overflow else 0)),
            True,
        )

    return make_sub_epoch_summary(
        constants,
        blocks,
        uint32(prev_b.height + 2),
        prev_b,
        next_difficulty,
        next_sub_slot_iters,
    )
