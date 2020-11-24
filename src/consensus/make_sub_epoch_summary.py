from typing import Dict, Optional, Union

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_ip_iters, calculate_sp_iters, is_overflow_sub_block
from src.consensus.deficit import calculate_deficit
from src.consensus.difficulty_adjustment import get_next_ips, finishes_sub_epoch, get_next_difficulty
from src.full_node.sub_block_record import SubBlockRecord
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.ints import uint32, uint64, uint8, uint128


def make_sub_epoch_summary(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    blocks_included_height: uint32,
    prev_prev_sub_block: bytes32,
    new_difficulty: Optional[uint64],
    new_ips: Optional[uint64],
) -> SubEpochSummary:
    """
    Creates a sub-epoch-summary object, assuming that the first sub-block in the new sub-epoch is at height
    "blocks_included_height". Prev_sb is the last sub block in the previous sub-epoch. On a new epoch,
    new_difficulty and new_ips are also added.
    """
    assert prev_sb.height == blocks_included_height - 1
    # if first sub_epoch
    if blocks_included_height // constants.SUB_EPOCH_SUB_BLOCKS == 1:
        return SubEpochSummary(constants.GENESIS_SES_HASH, constants.FIRST_RC_CHALLENGE, uint8(0), None, None)

    curr = prev_sb
    while curr.sub_epoch_summary_included is None:
        curr = sub_blocks[curr.prev_hash]
    assert curr.sub_epoch_summary_included is not None
    prev_ses = curr.sub_epoch_summary_included.get_hash()
    ses = SubEpochSummary(
        prev_ses,
        curr.finished_reward_slot_hashes[-1],
        curr.height % constants.SUB_EPOCH_SUB_BLOCKS,
        new_difficulty,
        new_ips,
    )

    assert ses is not None
    return ses


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
        ips = constants.IPS_STARTING
    else:
        assert prev_sb is not None
        ips = get_next_ips(
            constants,
            sub_blocks,
            height_to_hash,
            block.prev_header_hash,
            prev_sb.height,
            prev_sb.ips,
            prev_sb.deficit,
            len(block.finished_sub_slots) > 0,
            prev_sb.sp_total_iters(constants),
        )
    overflow = is_overflow_sub_block(constants, signage_point_index)
    deficit = calculate_deficit(constants, block.height, prev_sb, overflow, len(block.finished_sub_slots) > 0)
    finishes_se = finishes_sub_epoch(
        constants, block.height, deficit, False, sub_blocks, prev_sb.header_hash if prev_sb is not None else None
    )
    finishes_epoch: bool = finishes_sub_epoch(
        constants, block.height, deficit, True, sub_blocks, prev_sb.header_hash if prev_sb is not None else None
    )

    if finishes_se:
        assert prev_sb is not None
        if finishes_epoch:
            sp_iters = calculate_sp_iters(constants, ips, signage_point_index)
            ip_iters = calculate_ip_iters(constants, ips, signage_point_index, required_iters)
            next_difficulty = get_next_difficulty(
                constants,
                sub_blocks,
                height_to_hash,
                block.header_hash,
                block.height,
                uint64(block.weight - prev_sb.weight),
                deficit,
                True,
                uint128(block.total_iters - ip_iters + sp_iters),
            )
            next_ips = get_next_ips(
                constants,
                sub_blocks,
                height_to_hash,
                block.header_hash,
                block.height,
                ips,
                deficit,
                True,
                uint128(block.total_iters - ip_iters + sp_iters),
            )
        else:
            next_difficulty = None
            next_ips = None
        return make_sub_epoch_summary(constants, sub_blocks, block.height + 1, prev_sb, next_difficulty, next_ips)
    return None
