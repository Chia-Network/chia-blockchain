from typing import Dict, Optional, Union

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_sp_iters,
    is_overflow_sub_block,
)
from src.consensus.deficit import calculate_deficit
from src.consensus.difficulty_adjustment import (
    can_finish_sub_and_full_epoch,
    get_next_difficulty,
    get_next_sub_slot_iters,
)
from src.consensus.sub_block_record import SubBlockRecord
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.ints import uint32, uint64, uint8, uint128


def make_sub_epoch_summary(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    blocks_included_height: uint32,
    prev_prev_sub_block: SubBlockRecord,
    new_difficulty: Optional[uint64],
    new_sub_slot_iters: Optional[uint64],
) -> SubEpochSummary:
    """
    Creates a sub-epoch-summary object, assuming that the first sub-block in the new sub-epoch is at height
    "blocks_included_height". Prev_sb is the last sub block in the previous sub-epoch. On a new epoch,
    new_difficulty and new_sub_slot_iters are also added.
    """
    assert prev_prev_sub_block.height == blocks_included_height - 2

    # If first sub_epoch
    if blocks_included_height // constants.SUB_EPOCH_SUB_BLOCKS == 1:
        return SubEpochSummary(constants.GENESIS_SES_HASH, constants.FIRST_RC_CHALLENGE, uint8(0), None, None)
    curr: SubBlockRecord = prev_prev_sub_block
    while curr.sub_epoch_summary_included is None:
        curr = sub_blocks[curr.prev_hash]
    assert curr.sub_epoch_summary_included is not None
    prev_ses = curr.sub_epoch_summary_included.get_hash()
    return SubEpochSummary(
        prev_ses,
        curr.finished_reward_slot_hashes[-1],
        uint8(curr.height % constants.SUB_EPOCH_SUB_BLOCKS),
        new_difficulty,
        new_sub_slot_iters,
    )


def next_sub_epoch_summary(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    signage_point_index: uint8,
    required_iters: uint64,
    block: Union[UnfinishedBlock, FullBlock],
) -> Optional[SubEpochSummary]:
    prev_sb: Optional[SubBlockRecord] = sub_blocks.get(block.prev_header_hash, None)
    if block.height == 0:
        return None

    assert prev_sb is not None
    # This is the ssi of the current block
    sub_slot_iters = get_next_sub_slot_iters(
        constants,
        sub_blocks,
        height_to_hash,
        prev_sb.prev_hash,
        prev_sb.height,
        prev_sb.sub_slot_iters,
        prev_sb.deficit,
        len(block.finished_sub_slots) > 0,
        prev_sb.sp_total_iters(constants),
    )
    overflow = is_overflow_sub_block(constants, signage_point_index)
    deficit = calculate_deficit(constants, block.height, prev_sb, overflow, len(block.finished_sub_slots) > 0)
    can_finish_se, can_finish_epoch = can_finish_sub_and_full_epoch(
        constants, block.height, deficit, sub_blocks, prev_sb.header_hash if prev_sb is not None else None
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
            sub_blocks,
            height_to_hash,
            block.prev_header_hash,
            block.height,
            uint64(block.weight - prev_sb.weight),
            deficit,
            True,
            uint128(block.total_iters - ip_iters + sp_iters - (sub_slot_iters if overflow else 0)),
        )
        next_sub_slot_iters = get_next_sub_slot_iters(
            constants,
            sub_blocks,
            height_to_hash,
            block.prev_header_hash,
            block.height,
            sub_slot_iters,
            deficit,
            True,
            uint128(block.total_iters - ip_iters + sp_iters - (sub_slot_iters if overflow else 0)),
        )

    return make_sub_epoch_summary(
        constants, sub_blocks, block.height + 1, prev_sb, next_difficulty, next_sub_slot_iters
    )
