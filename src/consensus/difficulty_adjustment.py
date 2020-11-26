from typing import Dict, List, Union, Optional

from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.unfinished_block import UnfinishedBlock
from src.types.unfinished_header_block import UnfinishedHeaderBlock

from src.consensus.constants import ConsensusConstants
from src.types.sized_bytes import bytes32
from src.full_node.sub_block_record import SubBlockRecord
from src.util.ints import uint32, uint64, uint128, uint8
from src.util.significant_bits import (
    count_significant_bits,
    truncate_to_significant_bits,
)


def _get_blocks_at_height(
    height_to_hash: Dict[uint32, bytes32],
    sub_blocks: Dict[bytes32, SubBlockRecord],
    prev_sb: SubBlockRecord,
    target_height: uint32,
    max_num_blocks: uint32 = 1,
) -> List[SubBlockRecord]:
    if height_to_hash[prev_sb.height] == prev_sb.header_hash:
        # Efficient fetching, since we are fetching ancestor blocks within the heaviest chain
        return [
            sub_blocks[height_to_hash[uint32(h)]]
            for h in range(target_height, target_height + max_num_blocks)
            if h in height_to_hash
        ]
    # slow fetching, goes back one by one
    curr_b: SubBlockRecord = prev_sb
    target_blocks = []
    while curr_b.height >= target_height:
        if curr_b.height < target_height + max_num_blocks:
            target_blocks.append(curr_b)
        if curr_b.height == 0:
            break
        curr_b = sub_blocks[curr_b.prev_hash]
    return list(reversed(target_blocks))


def _get_last_block_in_previous_epoch(
    constants: ConsensusConstants,
    next_height: uint32,
    height_to_hash: Dict[uint32, bytes32],
    sub_blocks: Dict[bytes32, SubBlockRecord],
    prev_sb: SubBlockRecord,
) -> SubBlockRecord:

    #       prev epoch surpassed  prev epoch started                  epoch sur.  epoch started
    #        v                       v                                v         v
    #  |.B...B....B. B....B...|......B....B.....B...B.|.B.B.B..|..B...B.B.B...|.B.B.B. B.|........

    # The sub-blocks selected for the timestamps are the last sub-block which is also a block, and which is infused
    # before the final sub-block in the epoch. Block at height 0 is an exception.
    # TODO: check edge cases here
    height_epoch_surpass: uint32 = next_height - (next_height % constants.EPOCH_SUB_BLOCKS)
    if (next_height - height_epoch_surpass) > constants.MAX_SLOT_SUB_BLOCKS:
        raise ValueError(f"Height at {next_height} should not create a new slot, it is far past the epoch barrier")

    height_prev_epoch_surpass: uint32 = height_epoch_surpass - constants.EPOCH_SUB_BLOCKS
    if height_prev_epoch_surpass == 0:
        # The genesis block is an edge case, where we measure from the first block in epoch (height 0), as opposed to
        # the last sub-block in the previous epoch, which would be height -1
        return _get_blocks_at_height(height_to_hash, sub_blocks, prev_sb, uint32(0))[0]

    # If the prev slot is the first slot, the iterations start at 0
    # We will compute the timestamps of the last block in epoch, as well as the total iterations at infusion
    first_sb_in_epoch: SubBlockRecord
    prev_slot_start_iters: uint128
    prev_slot_time_start: uint64

    fetched_blocks = _get_blocks_at_height(
        height_to_hash,
        sub_blocks,
        prev_sb,
        uint32(height_prev_epoch_surpass - constants.MAX_SLOT_SUB_BLOCKS - 1),
        uint32(2 * constants.MAX_SLOT_SUB_BLOCKS + 1),
    )
    # This is the last sb in the slot at which we surpass the height. The last block in epoch will be before this.
    fetched_index: int = constants.MAX_SLOT_SUB_BLOCKS
    last_sb_in_slot: SubBlockRecord = fetched_blocks[fetched_index]
    fetched_index += 1
    assert last_sb_in_slot.height == height_prev_epoch_surpass - 1
    curr: SubBlockRecord = fetched_blocks[fetched_index]
    # Wait until the slot finishes with a challenge chain infusion at start of slot
    # Note that there are no overflow blocks at the start of new epochs
    while not curr.is_challenge_sub_block(constants):
        last_sb_in_slot = curr
        curr = fetched_blocks[fetched_index]
        fetched_index += 1

    # Backtrack to find the last block before the signage point
    curr = sub_blocks[last_sb_in_slot.prev_hash]
    while curr.total_iters > last_sb_in_slot.sp_total_iters(constants) or not curr.is_block:
        curr = sub_blocks[curr.prev_hash]

    return curr


def can_finish_sub_and_full_epoch(
    constants: ConsensusConstants,
    height: uint32,
    deficit: uint8,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    prev_header_hash: Optional[bytes32],
) -> (bool, bool):
    """
    Returns a bool tuple
    first bool is true if the next sub-slot after height will form part of a new sub-epoch and epoch.
    second bool is true if the next sub-slot after height will form part of a new sub-epoch and epoch.
    Warning: This assumes the previous sub-block did not finish a sub-epoch. TODO: check
    """

    if height < constants.SUB_EPOCH_SUB_BLOCKS - 1:
        return False, False

    assert prev_header_hash is not None

    # If last slot does not have enough blocks for a new challenge chain infusion, return same difficulty
    if deficit > 0:
        return False, False

    # Disqualify blocks which are too far past in height
    # The maximum possible height which includes sub epoch summary
    if (height + 1) % constants.SUB_EPOCH_SUB_BLOCKS > constants.MAX_SLOT_SUB_BLOCKS:
        return False, False

    # For sub-blocks which equal 0 or 1, we assume that the sub-epoch has not been finished yet
    if (height + 1) % constants.SUB_EPOCH_SUB_BLOCKS > 1:
        already_included_ses = False
        curr: SubBlockRecord = sub_blocks[prev_header_hash]
        while curr.height % constants.SUB_EPOCH_SUB_BLOCKS > 0:
            if curr.sub_epoch_summary_included is not None:
                already_included_ses = True
                break
            curr = sub_blocks[curr.prev_hash]

        if already_included_ses or (curr.sub_epoch_summary_included is not None):
            return False, False

    # For checking new epoch, make sure the epoch sub blocks are aligned
    if (height + 1) % constants.EPOCH_SUB_BLOCKS > constants.MAX_SLOT_SUB_BLOCKS:
        return True, False

    return True, True


def get_next_sub_slot_iters(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    prev_header_hash: bytes32,
    height: uint32,
    curr_sub_slot_iters: uint64,
    deficit: uint8,
    new_slot: bool,
    signage_point_total_iters: uint128,
) -> uint64:
    """
    Returns the slot iterations required for the next block after header hash, where new_slot is true iff
    the next block will be in the next slot.
    """
    next_height: uint32 = uint32(height + 1)

    if next_height < constants.EPOCH_SUB_BLOCKS:
        return uint64(constants.SUB_SLOT_ITERS_STARTING)

    if prev_header_hash not in sub_blocks:
        raise ValueError(f"Header hash {prev_header_hash} not in sub blocks")

    prev_sb: SubBlockRecord = sub_blocks[prev_header_hash]

    # If we are in the same epoch, return same ssi
    _, can_finish_epoch = can_finish_sub_and_full_epoch(constants, height, deficit, sub_blocks, prev_header_hash)
    if not new_slot or not can_finish_epoch:
        return curr_sub_slot_iters

    last_block_prev: SubBlockRecord = _get_last_block_in_previous_epoch(
        constants, next_height, height_to_hash, sub_blocks, prev_sb
    )

    # Ensure we get a block for the last block as well, and that it is before the signage point
    last_block_curr = prev_sb
    while last_block_curr.total_iters > signage_point_total_iters or not last_block_curr.is_block:
        last_block_curr = sub_blocks[last_block_curr.prev_hash]

    # This is computed as the iterations per second in last epoch, times the target number of seconds per slot
    new_ssi_precise: uint64 = uint64(
        constants.SUB_SLOT_TIME_TARGET
        * (last_block_curr.total_iters - last_block_prev.total_iters)
        // (last_block_curr.timestamp - last_block_prev.timestamp)
    )
    new_ssi = uint64(truncate_to_significant_bits(new_ssi_precise, constants.SIGNIFICANT_BITS))

    # Only change by a max factor as a sanity check
    max_ssi = uint64(
        truncate_to_significant_bits(
            constants.DIFFICULTY_FACTOR * last_block_curr.sub_slot_iters,
            constants.SIGNIFICANT_BITS,
        )
    )
    min_ssi = uint64(
        truncate_to_significant_bits(
            last_block_curr.sub_slot_iters // constants.DIFFICULTY_FACTOR,
            constants.SIGNIFICANT_BITS,
        )
    )
    if new_ssi >= last_block_curr.sub_slot_iters:
        new_ssi = min(new_ssi, max_ssi)
    else:
        new_ssi = max([constants.NUM_SPS_SUB_SLOT, new_ssi, min_ssi])

    new_ssi = uint64(new_ssi - new_ssi % constants.NUM_SPS_SUB_SLOT)  # Must divide the sub slot
    assert count_significant_bits(new_ssi) <= constants.SIGNIFICANT_BITS
    return new_ssi


def get_next_difficulty(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    prev_header_hash: bytes32,
    height: uint32,
    current_difficulty: uint64,
    deficit: uint8,
    new_slot: bool,
    signage_point_total_iters: uint128,
) -> uint64:
    """
    Returns the difficulty of the next sub-block that extends onto sub-block.
    Used to calculate the number of iterations. When changing this, also change the implementation
    in wallet_state_manager.py.
    """
    next_height: uint32 = uint32(height + 1)

    if next_height < constants.EPOCH_SUB_BLOCKS:
        # We are in the first epoch
        return uint64(constants.DIFFICULTY_STARTING)

    if prev_header_hash not in sub_blocks:
        raise ValueError(f"Header hash {prev_header_hash} not in sub blocks")

    prev_sb: SubBlockRecord = sub_blocks[prev_header_hash]

    # If we are in the same slot as previous sub-block, return same difficulty
    can_finish_se, _ = can_finish_sub_and_full_epoch(constants, height, deficit, sub_blocks, prev_header_hash)
    if not new_slot or not can_finish_se:
        return current_difficulty

    last_block_prev: SubBlockRecord = _get_last_block_in_previous_epoch(
        constants, next_height, height_to_hash, sub_blocks, prev_sb
    )

    # Ensure we get a block for the last block as well, and that it is before the signage point
    last_block_curr = prev_sb
    while last_block_curr.total_iters > signage_point_total_iters or not last_block_curr.is_block:
        last_block_curr = sub_blocks[last_block_curr.prev_hash]

    actual_epoch_time = last_block_curr.timestamp - last_block_prev.timestamp
    old_difficulty = uint64(prev_sb.weight - sub_blocks[prev_sb.prev_hash].weight)

    # Terms are rearranged so there is only one division.
    new_difficulty_precise = (
        (last_block_curr.weight - last_block_prev.weight)
        * constants.SUB_SLOT_TIME_TARGET
        // (constants.SLOT_SUB_BLOCKS_TARGET * actual_epoch_time)
    )
    # Take only DIFFICULTY_SIGNIFICANT_BITS significant bits
    new_difficulty = uint64(truncate_to_significant_bits(new_difficulty_precise, constants.SIGNIFICANT_BITS))
    assert count_significant_bits(new_difficulty) <= constants.SIGNIFICANT_BITS

    # Only change by a max factor, to prevent attacks, as in greenpaper, and must be at least 1
    max_diff = uint64(
        truncate_to_significant_bits(
            constants.DIFFICULTY_FACTOR * old_difficulty,
            constants.SIGNIFICANT_BITS,
        )
    )
    min_diff = uint64(
        truncate_to_significant_bits(
            old_difficulty // constants.DIFFICULTY_FACTOR,
            constants.SIGNIFICANT_BITS,
        )
    )
    if new_difficulty >= old_difficulty:
        return min(new_difficulty, max_diff)
    else:
        return max([uint64(1), new_difficulty, min_diff])


def cc_sp_hash(args):
    pass


def get_sub_slot_iters_and_difficulty(
    constants: ConsensusConstants,
    header_block: Union[UnfinishedHeaderBlock, UnfinishedBlock, HeaderBlock, FullBlock],
    height_to_hash: Dict[uint32, bytes32],
    prev_sb: SubBlockRecord,
    sub_blocks: Dict[bytes32, SubBlockRecord],
) -> (uint64, uint64):
    # genesis
    if prev_sb is None:
        return constants.SUB_SLOT_ITERS_STARTING, constants.DIFFICULTY_STARTING

    if prev_sb.height != 0:
        prev_difficulty: uint64 = uint64(prev_sb.weight - sub_blocks[prev_sb.prev_hash].weight)
    else:
        # prev block is genesis
        prev_difficulty: uint64 = uint64(prev_sb.weight)

    sp_total_iters = prev_sb.sp_total_iters(constants)
    difficulty: uint64 = get_next_difficulty(
        constants,
        sub_blocks,
        height_to_hash,
        prev_sb.prev_hash,
        prev_sb.height,
        prev_difficulty,
        prev_sb.deficit,
        len(header_block.finished_sub_slots) > 0,
        sp_total_iters,
    )

    sub_slot_iters: uint64 = get_next_sub_slot_iters(
        constants,
        sub_blocks,
        height_to_hash,
        prev_sb.prev_hash,
        prev_sb.height,
        prev_sb.sub_slot_iters,
        prev_sb.deficit,
        len(header_block.finished_sub_slots) > 0,
        sp_total_iters,
    )

    return sub_slot_iters, difficulty
