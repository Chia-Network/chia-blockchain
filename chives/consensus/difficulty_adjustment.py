from typing import List, Optional, Tuple

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.significant_bits import count_significant_bits, truncate_to_significant_bits


def _get_blocks_at_height(
    blocks: BlockchainInterface,
    prev_b: BlockRecord,
    target_height: uint32,
    max_num_blocks: uint32 = uint32(1),
) -> List[BlockRecord]:
    """
    Return a consecutive list of BlockRecords starting at target_height, returning a maximum of
    max_num_blocks. Assumes all block records are present. Does a slot linear search, if the blocks are not
    in the path of the peak. Can only fetch ancestors of prev_b.

    Args:
        blocks: dict from header hash to BlockRecord.
        prev_b: prev_b (to start backwards search).
        target_height: target block to start
        max_num_blocks: max number of blocks to fetch (although less might be fetched)

    """
    if blocks.contains_height(prev_b.height):
        header_hash = blocks.height_to_hash(prev_b.height)
        if header_hash == prev_b.header_hash:
            # Efficient fetching, since we are fetching ancestor blocks within the heaviest chain. We can directly
            # use the height_to_block_record method
            block_list: List[BlockRecord] = []
            for h in range(target_height, target_height + max_num_blocks):
                assert blocks.contains_height(uint32(h))
                block_list.append(blocks.height_to_block_record(uint32(h)))
            return block_list

    # Slow fetching, goes back one by one, since we are in a fork
    curr_b: BlockRecord = prev_b
    target_blocks = []
    while curr_b.height >= target_height:
        if curr_b.height < target_height + max_num_blocks:
            target_blocks.append(curr_b)
        if curr_b.height == 0:
            break
        curr_b = blocks.block_record(curr_b.prev_hash)
    return list(reversed(target_blocks))


def _get_second_to_last_transaction_block_in_previous_epoch(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    last_b: BlockRecord,
) -> BlockRecord:
    """
    Retrieves the second to last transaction block in the previous epoch.

    Args:
        constants: consensus constants being used for this chain
        blocks: dict from header hash to block of all relevant blocks
        last_b: last-block in the current epoch, or last block we have seen, if potentially finishing epoch soon

           prev epoch surpassed  prev epoch started                  epoch sur.  epoch started
            v                       v                                v         v
      |.B...B....B. B....B...|......B....B.....B...B.|.B.B.B..|..B...B.B.B...|.B.B.B. B.|........
            PREV EPOCH                 CURR EPOCH                               NEW EPOCH

     The blocks selected for the timestamps are the second to last transaction blocks in each epoch.
     Block at height 0 is an exception. Note that H mod EPOCH_BLOCKS where H is the height of the first block in the
     epoch, must be >= 0, and < 128.
    """

    # This height is guaranteed to be in the next epoch (even when last_b is not actually the last block)
    height_in_next_epoch = (
        last_b.height + 2 * constants.MAX_SUB_SLOT_BLOCKS + constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK + 5
    )
    height_epoch_surpass: uint32 = uint32(height_in_next_epoch - (height_in_next_epoch % constants.EPOCH_BLOCKS))
    height_prev_epoch_surpass: uint32 = uint32(height_epoch_surpass - constants.EPOCH_BLOCKS)

    assert height_prev_epoch_surpass % constants.EPOCH_BLOCKS == height_prev_epoch_surpass % constants.EPOCH_BLOCKS == 0

    # Sanity check, don't go too far past epoch barrier
    assert (height_in_next_epoch - height_epoch_surpass) < (5 * constants.MAX_SUB_SLOT_BLOCKS)

    if height_prev_epoch_surpass == 0:
        # The genesis block is an edge case, where we measure from the first block in epoch (height 0), as opposed to
        # a block in the previous epoch, which would be height < 0
        return _get_blocks_at_height(blocks, last_b, uint32(0))[0]

    # If the prev slot is the first slot, the iterations start at 0
    # We will compute the timestamps of the 2nd to last block in epoch, as well as the total iterations at infusion
    prev_slot_start_iters: uint128
    prev_slot_time_start: uint64

    # The target block must be in this range. Either the surpass block must be a transaction block, or something
    # in it's sub slot must be a transaction block. If that is the only transaction block in the sub-slot, the last
    # block in the previous sub-slot from that must also be a transaction block (therefore -1 is used).
    # The max height for the new epoch to start is surpass + 2*MAX_SUB_SLOT_BLOCKS + MIN_BLOCKS_PER_CHALLENGE_BLOCK - 3,
    # since we might have a deficit > 0 when surpass is hit. The +3 is added just in case
    fetched_blocks = _get_blocks_at_height(
        blocks,
        last_b,
        uint32(height_prev_epoch_surpass - constants.MAX_SUB_SLOT_BLOCKS - 1),
        uint32(3 * constants.MAX_SUB_SLOT_BLOCKS + constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK + 3),
    )

    # We want to find the last block in the slot at which we surpass the height.
    # The last block in epoch will be before this.
    fetched_index: int = constants.MAX_SUB_SLOT_BLOCKS
    curr_b: BlockRecord = fetched_blocks[fetched_index]
    fetched_index += 1
    assert curr_b.height == height_prev_epoch_surpass - 1
    next_b: BlockRecord = fetched_blocks[fetched_index]
    assert next_b.height == height_prev_epoch_surpass

    # Wait until the slot finishes with a challenge chain infusion at start of slot
    # Note that there are no overflow blocks at the start of new epochs
    while next_b.sub_epoch_summary_included is None:
        curr_b = next_b
        next_b = fetched_blocks[fetched_index]
        fetched_index += 1

    # Backtrack to find the second to last tx block
    found_tx_block = 1 if curr_b.is_transaction_block else 0
    while found_tx_block < 2:
        curr_b = blocks.block_record(curr_b.prev_hash)
        if curr_b.is_transaction_block:
            found_tx_block += 1

    return curr_b


def height_can_be_first_in_epoch(constants: ConsensusConstants, height: uint32) -> bool:
    return (height - (height % constants.SUB_EPOCH_BLOCKS)) % constants.EPOCH_BLOCKS == 0


def can_finish_sub_and_full_epoch(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    height: uint32,
    prev_header_hash: Optional[bytes32],
    deficit: uint8,
    block_at_height_included_ses: bool,
) -> Tuple[bool, bool]:
    """
    Returns a bool tuple
    first bool is true if the next sub-slot after height will form part of a new sub-epoch. Therefore
    block height is the last block, and height + 1 is in a new sub-epoch.
    second bool is true if the next sub-slot after height will form part of a new sub-epoch and epoch.
    Therefore, block height is the last block, and height + 1 is in a new epoch.

    Args:
        constants: consensus constants being used for this chain
        blocks: dictionary from header hash to SBR of all included SBR
        height: block height of the (potentially) last block in the sub-epoch
        prev_header_hash: prev_header hash of the block at height, assuming not genesis
        deficit: deficit of block at height height
        block_at_height_included_ses: whether or not the block at height height already included a SES
    """

    if height < constants.SUB_EPOCH_BLOCKS - 1:
        return False, False

    assert prev_header_hash is not None

    if deficit > 0:
        return False, False

    if block_at_height_included_ses:
        # If we just included a sub_epoch_summary, we cannot include one again
        return False, False

    # This does not check the two edge cases where (height + 1) % constants.SUB_EPOCH_BLOCKS is 0 or 1
    # If it's 0, height+1 is the first place that a sub-epoch can be included
    # If it's 1, we just checked whether 0 included it in the previous check
    if (height + 1) % constants.SUB_EPOCH_BLOCKS > 1:
        curr: BlockRecord = blocks.block_record(prev_header_hash)
        while curr.height % constants.SUB_EPOCH_BLOCKS > 0:
            if curr.sub_epoch_summary_included is not None:
                return False, False
            curr = blocks.block_record(curr.prev_hash)

        if curr.sub_epoch_summary_included is not None:
            return False, False

    # For checking new epoch, make sure the epoch blocks are aligned
    return True, height_can_be_first_in_epoch(constants, uint32(height + 1))


def _get_next_sub_slot_iters(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    prev_header_hash: bytes32,
    height: uint32,
    curr_sub_slot_iters: uint64,
    deficit: uint8,
    block_at_height_included_ses: bool,
    new_slot: bool,
    signage_point_total_iters: uint128,
    skip_epoch_check=False,
) -> uint64:
    """
    Returns the slot iterations required for the next block after the one at height, where new_slot is true
    iff the next block will be in the next slot. WARNING: assumes that the block at height is not the first block
    in a sub-epoch.

    Args:
        constants: consensus constants being used for this chain
        blocks: dictionary from header hash to SBR of all included SBR
        prev_header_hash: header hash of the previous block
        height: the block height of the block to look at
        curr_sub_slot_iters: sub-slot iters at the infusion point of the block at height
        deficit: deficit of block at height height
        new_slot: whether or not there is a new slot after height
        signage_point_total_iters: signage point iters of the block at height
        skip_epoch_check: don't check correct epoch
    """
    next_height: uint32 = uint32(height + 1)

    if next_height < constants.EPOCH_BLOCKS:
        return uint64(constants.SUB_SLOT_ITERS_STARTING)

    if not blocks.contains_block(prev_header_hash):
        raise ValueError(f"Header hash {prev_header_hash} not in blocks")

    prev_b: BlockRecord = blocks.block_record(prev_header_hash)

    # If we are in the same epoch, return same ssi
    if not skip_epoch_check:
        _, can_finish_epoch = can_finish_sub_and_full_epoch(
            constants, blocks, height, prev_header_hash, deficit, block_at_height_included_ses
        )
        if not new_slot or not can_finish_epoch:
            return curr_sub_slot_iters

    last_block_prev: BlockRecord = _get_second_to_last_transaction_block_in_previous_epoch(constants, blocks, prev_b)

    # This gets the last transaction block before this block's signage point. Assuming the block at height height
    # is the last block infused in the epoch: If this block ends up being a
    # transaction block, then last_block_curr will be the second to last tx block in the epoch. If this block
    # is not a transaction block, that means there was exactly one other tx block included in between our signage
    # point and infusion point, and therefore last_block_curr is the second to last as well.
    last_block_curr = prev_b
    while last_block_curr.total_iters > signage_point_total_iters or not last_block_curr.is_transaction_block:
        last_block_curr = blocks.block_record(last_block_curr.prev_hash)
    assert last_block_curr.timestamp is not None and last_block_prev.timestamp is not None

    # This is computed as the iterations per second in last epoch, times the target number of seconds per slot
    new_ssi_precise: uint64 = uint64(
        constants.SUB_SLOT_TIME_TARGET
        * (last_block_curr.total_iters - last_block_prev.total_iters)
        // (last_block_curr.timestamp - last_block_prev.timestamp)
    )

    # Only change by a max factor as a sanity check
    max_ssi = uint64(constants.DIFFICULTY_CHANGE_MAX_FACTOR * last_block_curr.sub_slot_iters)
    min_ssi = uint64(last_block_curr.sub_slot_iters // constants.DIFFICULTY_CHANGE_MAX_FACTOR)
    if new_ssi_precise >= last_block_curr.sub_slot_iters:
        new_ssi_precise = uint64(min(new_ssi_precise, max_ssi))
    else:
        new_ssi_precise = uint64(max([constants.NUM_SPS_SUB_SLOT, new_ssi_precise, min_ssi]))

    new_ssi = truncate_to_significant_bits(new_ssi_precise, constants.SIGNIFICANT_BITS)
    new_ssi = uint64(new_ssi - new_ssi % constants.NUM_SPS_SUB_SLOT)  # Must divide the sub slot
    assert count_significant_bits(new_ssi) <= constants.SIGNIFICANT_BITS
    return new_ssi


def _get_next_difficulty(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    prev_header_hash: bytes32,
    height: uint32,
    current_difficulty: uint64,
    deficit: uint8,
    block_at_height_included_ses: bool,
    new_slot: bool,
    signage_point_total_iters: uint128,
    skip_epoch_check=False,
) -> uint64:
    """
    Returns the difficulty of the next block that extends onto block.
    Used to calculate the number of iterations. WARNING: assumes that the block at height is not the first block
    in a sub-epoch.

    Args:
        constants: consensus constants being used for this chain
        blocks: dictionary from header hash to SBR of all included SBR
        prev_header_hash: header hash of the previous block
        height: the block height of the block to look at
        deficit: deficit of block at height height
        current_difficulty: difficulty at the infusion point of the block at height
        new_slot: whether or not there is a new slot after height
        signage_point_total_iters: signage point iters of the block at height
        skip_epoch_check: don't check correct epoch
    """
    next_height: uint32 = uint32(height + 1)

    if next_height < (constants.EPOCH_BLOCKS - 3 * constants.MAX_SUB_SLOT_BLOCKS):
        # We are in the first epoch
        return uint64(constants.DIFFICULTY_STARTING)

    if not blocks.contains_block(prev_header_hash):
        raise ValueError(f"Header hash {prev_header_hash} not in blocks")

    prev_b: BlockRecord = blocks.block_record(prev_header_hash)

    # If we are in the same slot as previous block, return same difficulty
    if not skip_epoch_check:
        _, can_finish_epoch = can_finish_sub_and_full_epoch(
            constants, blocks, height, prev_header_hash, deficit, block_at_height_included_ses
        )
        if not new_slot or not can_finish_epoch:
            return current_difficulty

    last_block_prev: BlockRecord = _get_second_to_last_transaction_block_in_previous_epoch(constants, blocks, prev_b)

    # This gets the last transaction block before this block's signage point. Assuming the block at height height
    # is the last block infused in the epoch: If this block ends up being a
    # transaction block, then last_block_curr will be the second to last tx block in the epoch. If this block
    # is not a transaction block, that means there was exactly one other tx block included in between our signage
    # point and infusion point, and therefore last_block_curr is the second to last as well.
    last_block_curr = prev_b
    while last_block_curr.total_iters > signage_point_total_iters or not last_block_curr.is_transaction_block:
        last_block_curr = blocks.block_record(last_block_curr.prev_hash)

    assert last_block_curr.timestamp is not None
    assert last_block_prev.timestamp is not None
    actual_epoch_time: uint64 = uint64(last_block_curr.timestamp - last_block_prev.timestamp)

    old_difficulty = uint64(prev_b.weight - blocks.block_record(prev_b.prev_hash).weight)

    # Terms are rearranged so there is only one division.
    new_difficulty_precise = uint64(
        (last_block_curr.weight - last_block_prev.weight)
        * constants.SUB_SLOT_TIME_TARGET
        // (constants.SLOT_BLOCKS_TARGET * actual_epoch_time)
    )

    # Only change by a max factor, to prevent attacks, as in greenpaper, and must be at least 1
    max_diff = uint64(constants.DIFFICULTY_CHANGE_MAX_FACTOR * old_difficulty)
    min_diff = uint64(old_difficulty // constants.DIFFICULTY_CHANGE_MAX_FACTOR)

    if new_difficulty_precise >= old_difficulty:
        new_difficulty_precise = uint64(min(new_difficulty_precise, max_diff))
    else:
        new_difficulty_precise = uint64(max([uint64(1), new_difficulty_precise, min_diff]))
    new_difficulty = truncate_to_significant_bits(new_difficulty_precise, constants.SIGNIFICANT_BITS)
    assert count_significant_bits(new_difficulty) <= constants.SIGNIFICANT_BITS
    return uint64(new_difficulty)


def get_next_sub_slot_iters_and_difficulty(
    constants: ConsensusConstants,
    is_first_in_sub_slot: bool,
    prev_b: Optional[BlockRecord],
    blocks: BlockchainInterface,
) -> Tuple[uint64, uint64]:
    """
    Retrieves the current sub_slot iters and difficulty of the next block after prev_b.

    Args:
        constants: consensus constants being used for this chain
        is_first_in_sub_slot: Whether the next block is the first in the sub slot
        prev_b: the previous block (last block in the epoch)
        blocks: dictionary from header hash to SBR of all included SBR

    """

    # genesis
    if prev_b is None:
        return constants.SUB_SLOT_ITERS_STARTING, constants.DIFFICULTY_STARTING

    if prev_b.height != 0:
        prev_difficulty: uint64 = uint64(prev_b.weight - blocks.block_record(prev_b.prev_hash).weight)
    else:
        # prev block is genesis
        prev_difficulty = uint64(prev_b.weight)

    if prev_b.sub_epoch_summary_included is not None:
        return prev_b.sub_slot_iters, prev_difficulty

    sp_total_iters = prev_b.sp_total_iters(constants)
    difficulty: uint64 = _get_next_difficulty(
        constants,
        blocks,
        prev_b.prev_hash,
        prev_b.height,
        prev_difficulty,
        prev_b.deficit,
        False,  # Already checked above
        is_first_in_sub_slot,
        sp_total_iters,
    )

    sub_slot_iters: uint64 = _get_next_sub_slot_iters(
        constants,
        blocks,
        prev_b.prev_hash,
        prev_b.height,
        prev_b.sub_slot_iters,
        prev_b.deficit,
        False,  # Already checked above
        is_first_in_sub_slot,
        sp_total_iters,
    )

    return sub_slot_iters, difficulty
