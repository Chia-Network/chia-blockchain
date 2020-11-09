from typing import Dict, List

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_sp_iters, calculate_ip_iters
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
        curr_b = sub_blocks[curr_b.prev_hash]
    return target_blocks


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
    height_epoch_surpass: uint32 = next_height % constants.EPOCH_SUB_BLOCKS
    if height_epoch_surpass > constants.MAX_SLOT_SUB_BLOCKS:
        raise ValueError(f"Height at {next_height} should not create a new slot, it is far past the epoch barrier")

    # If the prev slot is the first slot, the iterations start at 0
    # We will compute the timestamps of the last block in epoch, as well as the total iterations at infusion
    first_sb_in_epoch: SubBlockRecord
    prev_slot_start_iters: uint128
    prev_slot_time_start: uint64

    if height_epoch_surpass == 0:
        # The genesis block is an edge case, where we measure from the first block in epoch, as opposed to the last
        # block in the previous epoch
        return _get_blocks_at_height(height_to_hash, sub_blocks, prev_sb, uint32(0))[1]
    else:
        fetched_blocks = _get_blocks_at_height(
            height_to_hash,
            sub_blocks,
            prev_sb,
            uint32(height_epoch_surpass - constants.EPOCH_SUB_BLOCKS - constants.MAX_SLOT_SUB_BLOCKS - 1),
            uint32(2 * constants.MAX_SLOT_SUB_BLOCKS + 1),
        )
        # This is the last sb in the slot at which we surpass the height. The last block in epoch will be before this.
        last_sb_in_slot: SubBlockRecord = fetched_blocks[constants.MAX_SLOT_SUB_BLOCKS]
        fetched_index: int = constants.MAX_SLOT_SUB_BLOCKS + 1
        curr: SubBlockRecord = fetched_blocks[fetched_index]
        # Wait until the slot finishes with a challenge chain infusion at start of slot
        while not curr.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
            last_sb_in_slot = curr
            curr = fetched_blocks[fetched_index]
            fetched_index += 1

        last_sb_ip_iters = calculate_ip_iters(constants, last_sb_in_slot.ips, last_sb_in_slot.required_iters)
        last_sb_sp_iters = calculate_sp_iters(constants, last_sb_in_slot.ips, last_sb_in_slot.required_iters)
        prev_signage_point_total_iters = last_sb_in_slot.total_iters - last_sb_ip_iters + last_sb_sp_iters

        # Backtrack to find the last block before the signage point
        curr = sub_blocks[last_sb_in_slot.prev_hash]
        while curr.total_iters > prev_signage_point_total_iters or not curr.is_block:
            curr = sub_blocks[curr.prev_hash]

        return curr


def finishes_sub_epoch(
    constants: ConsensusConstants,
    height: uint32,
    deficit: uint8,
    also_finishes_epoch: bool,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    prev_header_hash: bytes32,
) -> bool:
    """
    Returns true if the next sub-slot after height will form part of a new sub-epoch (or epoch if also_finished_epoch
    is set to True)
    """
    if height < constants.SUB_EPOCH_SUB_BLOCKS - 1:
        return False

    # If last slot does not have enough blocks for a new challenge chain infusion, return same difficulty
    if deficit > 0:
        return False

    # Disqualify blocks which are too far past in height
    # The maximum possible height which includes sub epoch summary
    if (height + 1) % constants.SUB_EPOCH_SUB_BLOCKS > constants.MAX_SLOT_SUB_BLOCKS:
        return False

    already_included_ses = False
    curr: SubBlockRecord = sub_blocks[prev_header_hash]
    while curr.height % constants.SUB_EPOCH_SUB_BLOCKS > 0:
        if curr.sub_epoch_summary_included is not None:
            already_included_ses = True
            break
        curr = sub_blocks[curr.prev_hash]

    if already_included_ses or (curr.sub_epoch_summary_included is not None):
        return False

    # For checking new epoch, make sure the epoch sub blocks are aligned
    if also_finishes_epoch:
        if height + 1 % constants.EPOCH_SUB_BLOCKS > constants.MAX_SLOT_SUB_BLOCKS:
            return False

    return True


def get_next_ips(
    constants: ConsensusConstants,
    height_to_hash: Dict[uint32, bytes32],
    sub_blocks: Dict[bytes32, SubBlockRecord],
    prev_header_hash: bytes32,
    height: uint32,
    deficit: uint8,
    ips: uint64,
    new_slot: bool,
    signage_point_total_iters: uint128,
) -> uint64:
    """
    Returns the slot iterations required for the next block after header hash, where new_slot is true iff
    the next block will be in the next slot.
    """
    next_height: uint32 = uint32(height + 1)

    if next_height < constants.EPOCH_SUB_BLOCKS:
        return uint64(constants.IPS_STARTING)

    if prev_header_hash not in sub_blocks:
        raise ValueError(f"Header hash {prev_header_hash} not in sub blocks")

    prev_sb: SubBlockRecord = sub_blocks[prev_header_hash]

    # If we are in the same epoch, return same ips
    if not new_slot or not finishes_sub_epoch(constants, height, deficit, True, sub_blocks, prev_header_hash):
        return ips

    last_block_prev: SubBlockRecord = _get_last_block_in_previous_epoch(
        constants, next_height, height_to_hash, sub_blocks, prev_sb
    )

    # Ensure we get a block for the last block as well, and that it is before the signage point
    last_block_curr = prev_sb
    while last_block_curr.total_iters > signage_point_total_iters or not last_block_curr.is_block:
        last_block_curr = sub_blocks[last_block_curr.prev_hash]

    # This is computed as the iterations per second in last epoch, times the target number of seconds per slot
    new_ips_precise: uint64 = uint64(
        (last_block_curr.total_iters - last_block_prev.total_iters)
        // (last_block_curr.timestamp - last_block_prev.timestamp)
    )
    assert count_significant_bits(new_ips) <= constants.SIGNIFICANT_BITS

    # Only change by a max factor as a sanity check
    max_ips = uint64(
        truncate_to_significant_bits(
            constants.DIFFICULTY_FACTOR * last_block_curr.ips,
            constants.SIGNIFICANT_BITS,
        )
    )
    min_ips = uint64(
        truncate_to_significant_bits(
            last_block_curr.ips // constants.DIFFICULTY_FACTOR,
            constants.SIGNIFICANT_BITS,
        )
    )
    if new_ips >= last_block_curr.ips:
        return min(new_ips, max_ips)
    else:
        return max([uint64(1), new_ips, min_ips])


def get_difficulty(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    header_hash: bytes32,
) -> uint64:
    """
    Returns the difficulty of the sub-block referred to by header_hash
    """
    sub_block = sub_blocks[header_hash]

    if sub_block.height == 0:
        return uint64(constants.DIFFICULTY_STARTING)
    return uint64(sub_block.weight - sub_blocks[sub_block.prev_hash].weight)


def get_next_difficulty(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    prev_header_hash: bytes32,
    height: uint32,
    deficit: uint8,
    current_difficulty: uint64,
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
    if not new_slot or not finishes_sub_epoch(constants, height, deficit, True, sub_blocks, prev_header_hash):
        return current_difficulty

    last_block_prev: SubBlockRecord = _get_last_block_in_previous_epoch(
        constants, next_height, height_to_hash, sub_blocks, prev_sb
    )

    # Ensure we get a block for the last block as well, and that it is before the signage point
    last_block_curr = prev_sb
    while last_block_curr.total_iters > signage_point_total_iters or not last_block_curr.is_block:
        last_block_curr = sub_blocks[last_block_curr.prev_hash]

    actual_epoch_time = last_block_curr.timestamp - last_block_prev.timestamp
    old_difficulty = get_difficulty(constants, sub_blocks, last_block_curr)

    # Terms are rearranged so there is only one division.
    new_difficulty_precise = (
        (last_block_curr.weight - last_block_prev.weight)
        * constants.SLOT_TIME_TARGET
        // (constants.SLOT_SUB_BLOCKS_TARGET * actual_epoch_time)
    )
    # Take only DIFFICULTY_SIGNIFICANT_BITS significant bits
    new_difficulty = uint64(
        truncate_to_significant_bits(new_difficulty_precise, constants.SIGNIFICANT_BITS)
    )
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
