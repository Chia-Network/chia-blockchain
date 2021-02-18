from typing import List, Union, Optional, Tuple

from src.consensus.blockchain_interface import BlockchainInterface
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.unfinished_block import UnfinishedBlock
from src.types.unfinished_header_block import UnfinishedHeaderBlock

from src.consensus.constants import ConsensusConstants
from src.types.blockchain_format.sized_bytes import bytes32
from src.consensus.block_record import BlockRecord
from src.util.ints import uint32, uint64, uint128, uint8
from src.util.significant_bits import (
    count_significant_bits,
    truncate_to_significant_bits,
)


def _get_blocks_at_height(
    blocks: BlockchainInterface,
    prev_b: BlockRecord,
    target_height: uint32,
    max_num_blocks: uint32 = uint32(1),
) -> List[BlockRecord]:
    """
    Return a consecutive list of BlockRecords starting at target_height, returning a maximum of
    max_num_blocks. Assumes all block records are present. Does a slot linear search, if the blocks are not
    in the path of the peak.

    Args:
        blocks: dict from header hash to BlockRecord.
        prev_b: prev_b (to start backwards search).
        target_height: target block to start
        max_num_blocks: max number of blocks to fetch (although less might be fetched)

    """
    if blocks.contains_height(prev_b.height):
        header_hash = blocks.height_to_hash(prev_b.height)
        if header_hash == prev_b.header_hash:
            # Efficient fetching, since we are fetching ancestor blocks within the heaviest chain
            block_list: List[BlockRecord] = []
            for h in range(target_height, target_height + max_num_blocks):
                assert blocks.contains_height(uint32(h))
                block_list.append(blocks.height_to_block_record(uint32(h)))
            return block_list
        # slow fetching, goes back one by one
    curr_b: BlockRecord = prev_b
    target_blocks = []
    while curr_b.height >= target_height:
        if curr_b.height < target_height + max_num_blocks:
            target_blocks.append(curr_b)
        if curr_b.height == 0:
            break
        curr_b = blocks.block_record(curr_b.prev_hash)
    return list(reversed(target_blocks))


def _get_last_transaction_block_in_previous_epoch(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    prev_b: BlockRecord,
) -> BlockRecord:
    """
    Retrieves the last transaction block (not block) in the previous epoch, which is infused before the last block in
    the epoch. This will be used for difficulty adjustment.

    Args:
        constants: consensus constants being used for this chain
        blocks: dict from header hash to block of all relevant blocks
        prev_b: last-block in the current epoch.

           prev epoch surpassed  prev epoch started                  epoch sur.  epoch started
            v                       v                                v         v
      |.B...B....B. B....B...|......B....B.....B...B.|.B.B.B..|..B...B.B.B...|.B.B.B. B.|........
            PREV EPOCH                 CURR EPOCH                               NEW EPOCH

     The blocks selected for the timestamps are the last block which is also a transaction block, and which
     is infused before the final block in the epoch. Block at height 0 is an exception.
    # TODO: check edge cases here
    """
    height_in_next_epoch = prev_b.height + constants.MAX_SUB_SLOT_BLOCKS + 3
    height_epoch_surpass: uint32 = uint32(height_in_next_epoch - (height_in_next_epoch % constants.EPOCH_BLOCKS))
    height_prev_epoch_surpass: uint32 = uint32(height_epoch_surpass - constants.EPOCH_BLOCKS)
    if (height_in_next_epoch - height_epoch_surpass) > (3 * constants.MAX_SUB_SLOT_BLOCKS):
        raise ValueError(
            f"Height at {prev_b.height + 1} should not create a new epoch, it is far past the epoch barrier"
        )

    if height_prev_epoch_surpass == 0:
        # The genesis block is an edge case, where we measure from the first block in epoch (height 0), as opposed to
        # the last block in the previous epoch, which would be height -1
        return _get_blocks_at_height(blocks, prev_b, uint32(0))[0]

    # If the prev slot is the first slot, the iterations start at 0
    # We will compute the timestamps of the last block in epoch, as well as the total iterations at infusion
    first_sb_in_epoch: BlockRecord
    prev_slot_start_iters: uint128
    prev_slot_time_start: uint64

    fetched_blocks = _get_blocks_at_height(
        blocks,
        prev_b,
        uint32(height_prev_epoch_surpass - constants.MAX_SUB_SLOT_BLOCKS - 1),
        uint32(2 * constants.MAX_SUB_SLOT_BLOCKS + 1),
    )

    # This is the last sb in the slot at which we surpass the height. The last block in epoch will be before this.
    fetched_index: int = constants.MAX_SUB_SLOT_BLOCKS
    last_sb_in_slot: BlockRecord = fetched_blocks[fetched_index]
    fetched_index += 1
    assert last_sb_in_slot.height == height_prev_epoch_surpass - 1
    curr_b: BlockRecord = fetched_blocks[fetched_index]
    assert curr_b.height == height_prev_epoch_surpass

    # Wait until the slot finishes with a challenge chain infusion at start of slot
    # Note that there are no overflow blocks at the start of new epochs
    while curr_b.sub_epoch_summary_included is None:
        last_sb_in_slot = curr_b
        curr_b = fetched_blocks[fetched_index]
        fetched_index += 1

    # Backtrack to find the last block before the signage point
    curr_b = blocks.block_record(last_sb_in_slot.prev_hash)
    while curr_b.total_iters > last_sb_in_slot.sp_total_iters(constants) or not curr_b.is_transaction_block:
        curr_b = blocks.block_record(curr_b.prev_hash)

    return curr_b


def can_finish_sub_and_full_epoch(
    constants: ConsensusConstants,
    height: uint32,
    deficit: uint8,
    blocks: BlockchainInterface,
    prev_header_hash: Optional[bytes32],
    can_finish_soon: bool = False,
) -> Tuple[bool, bool]:
    """
    Returns a bool tuple
    first bool is true if the next sub-slot after height will form part of a new sub-epoch. Therefore
    block height is the last block, and height + 1 is in a new sub-epoch.
    second bool is true if the next sub-slot after height will form part of a new sub-epoch and epoch.
    Therefore, block height is the last block, and height + 1 is in a new epoch.
    Warning: This assumes the previous block is not the last block in the sub-epoch (which means this
    current block does not include a sub epoch summary). TODO: check, simplify, and test code

    Args:
        constants: consensus constants being used for this chain
        height: block height of the (potentially) last block in the sub-epoch
        deficit: deficit of the block at height
        blocks: dictionary from header hash to SBR of all included SBR
        prev_header_hash: prev_header hash of the block at height, assuming not genesis
        can_finish_soon: this is useful when sending SES to timelords. We might not be able to finish it, but we will
            soon (within MAX_SUB_SLOT_BLOCKS)
    """

    if height < constants.SUB_EPOCH_BLOCKS - constants.MAX_SUB_SLOT_BLOCKS - 1:
        return False, False

    # Used along with "can_finish_soon"
    future_sb_height = height + constants.MAX_SUB_SLOT_BLOCKS + 1

    assert prev_header_hash is not None

    # If last slot does not have enough blocks for a new challenge chain infusion, return same difficulty
    if not can_finish_soon:
        if deficit > 0:
            return False, False

        # Disqualify blocks which are too far past in height
        # The maximum possible height which includes sub epoch summary
        if (height + 1) % constants.SUB_EPOCH_BLOCKS > constants.MAX_SUB_SLOT_BLOCKS:
            return False, False
        check_already_included = (height + 1) % constants.SUB_EPOCH_BLOCKS > 1
    else:
        # If can_finish_soon=True, we still want to make sure that we will be finishing a sub-epoch soon.
        # Here we check if a theoretical future block can finish the sub-epoch
        if (
            (height + 1) % constants.SUB_EPOCH_BLOCKS > constants.MAX_SUB_SLOT_BLOCKS
            and future_sb_height % constants.SUB_EPOCH_BLOCKS > constants.MAX_SUB_SLOT_BLOCKS
        ):
            return False, False
        # Don't check already included if we are not at the sub-epoch barrier yet.
        check_already_included = 1 < (height + 1) % constants.SUB_EPOCH_BLOCKS <= constants.MAX_SUB_SLOT_BLOCKS

    # For blocks which equal 0 or 1, we assume that the sub-epoch has not been finished yet
    if check_already_included:
        already_included_ses = False
        curr: BlockRecord = blocks.block_record(prev_header_hash)
        while curr.height % constants.SUB_EPOCH_BLOCKS > 0:
            if curr.sub_epoch_summary_included is not None:
                already_included_ses = True
                break
            curr = blocks.block_record(curr.prev_hash)

        if already_included_ses or (curr.sub_epoch_summary_included is not None):
            return False, False

    # For checking new epoch, make sure the epoch blocks are aligned
    if not can_finish_soon:
        if (height + 1) % constants.EPOCH_BLOCKS > constants.MAX_SUB_SLOT_BLOCKS:
            return True, False
    else:
        if (
            (height + 1) % constants.EPOCH_BLOCKS > constants.MAX_SUB_SLOT_BLOCKS
            and future_sb_height % constants.EPOCH_BLOCKS > constants.MAX_SUB_SLOT_BLOCKS
        ):
            return True, False

    return True, True


def get_next_sub_slot_iters(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    prev_header_hash: bytes32,
    height: uint32,
    curr_sub_slot_iters: uint64,
    deficit: uint8,
    new_slot: bool,
    signage_point_total_iters: uint128,
    skip_epoch_check=False,
) -> uint64:
    """
    Returns the slot iterations required for the next block after the one at height, where new_slot is true
    iff the next block will be in the next slot.

    Args:
        constants: consensus constants being used for this chain
        blocks: dictionary from header hash to SBR of all included SBR
        prev_header_hash: header hash of the previous block
        height: the block height of the block to look at
        curr_sub_slot_iters: sub-slot iters at the infusion point of the block at height
        deficit: deficit of the block at height
        new_slot: whether or not there is a new slot after height
        signage_point_total_iters: signage point iters of the block at height
        skip_epoch_check: don't check correct epoch
    """
    next_height: uint32 = uint32(height + 1)

    if next_height < (constants.EPOCH_BLOCKS - constants.MAX_SUB_SLOT_BLOCKS):
        return uint64(constants.SUB_SLOT_ITERS_STARTING)

    if not blocks.contains_block(prev_header_hash):
        raise ValueError(f"Header hash {prev_header_hash} not in blocks")

    prev_b: BlockRecord = blocks.block_record(prev_header_hash)

    # If we are in the same epoch, return same ssi
    if not skip_epoch_check:
        _, can_finish_epoch = can_finish_sub_and_full_epoch(constants, height, deficit, blocks, prev_header_hash, False)
        if not new_slot or not can_finish_epoch:
            return curr_sub_slot_iters

    last_block_prev: BlockRecord = _get_last_transaction_block_in_previous_epoch(constants, blocks, prev_b)

    # Ensure we get a tx block for the last block as well, and that it is before the signage point
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
    new_ssi = uint64(truncate_to_significant_bits(new_ssi_precise, constants.SIGNIFICANT_BITS))

    # Only change by a max factor as a sanity check
    max_ssi = uint64(
        truncate_to_significant_bits(
            constants.DIFFICULTY_CHANGE_MAX_FACTOR * last_block_curr.sub_slot_iters,
            constants.SIGNIFICANT_BITS,
        )
    )
    min_ssi = uint64(
        truncate_to_significant_bits(
            last_block_curr.sub_slot_iters // constants.DIFFICULTY_CHANGE_MAX_FACTOR,
            constants.SIGNIFICANT_BITS,
        )
    )
    if new_ssi >= last_block_curr.sub_slot_iters:
        new_ssi = min(new_ssi, max_ssi)
    else:
        new_ssi = uint64(max([constants.NUM_SPS_SUB_SLOT, new_ssi, min_ssi]))

    new_ssi = uint64(new_ssi - new_ssi % constants.NUM_SPS_SUB_SLOT)  # Must divide the sub slot
    assert count_significant_bits(new_ssi) <= constants.SIGNIFICANT_BITS
    return new_ssi


def get_next_difficulty(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    prev_header_hash: bytes32,
    height: uint32,
    current_difficulty: uint64,
    deficit: uint8,
    new_slot: bool,
    signage_point_total_iters: uint128,
    skip_epoch_check=False,
) -> uint64:
    """
    Returns the difficulty of the next block that extends onto block.
    Used to calculate the number of iterations. When changing this, also change the implementation
    in wallet_state_manager.py.

    Args:
        constants: consensus constants being used for this chain
        blocks: dictionary from header hash to SBR of all included SBR
        prev_header_hash: header hash of the previous block
        height: the block height of the block to look at
        current_difficulty: difficulty at the infusion point of the block at height
        deficit: deficit of the block at height
        new_slot: whether or not there is a new slot after height
        signage_point_total_iters: signage point iters of the block at height
        skip_epoch_check: don't check correct epoch
    """
    next_height: uint32 = uint32(height + 1)

    if next_height < (constants.EPOCH_BLOCKS - constants.MAX_SUB_SLOT_BLOCKS):
        # We are in the first epoch
        return uint64(constants.DIFFICULTY_STARTING)

    if not blocks.contains_block(prev_header_hash):
        raise ValueError(f"Header hash {prev_header_hash} not in blocks")

    prev_b: BlockRecord = blocks.block_record(prev_header_hash)

    # If we are in the same slot as previous block, return same difficulty
    if not skip_epoch_check:
        _, can_finish_epoch = can_finish_sub_and_full_epoch(constants, height, deficit, blocks, prev_header_hash, False)
        if not new_slot or not can_finish_epoch:
            return current_difficulty

    last_block_prev: BlockRecord = _get_last_transaction_block_in_previous_epoch(constants, blocks, prev_b)

    # Ensure we get a tx block for the last block as well, and that it is before the signage point
    last_block_curr = prev_b
    while last_block_curr.total_iters > signage_point_total_iters or not last_block_curr.is_transaction_block:
        last_block_curr = blocks.block_record(last_block_curr.prev_hash)

    assert last_block_curr.timestamp is not None
    assert last_block_prev.timestamp is not None
    actual_epoch_time: uint64 = uint64(last_block_curr.timestamp - last_block_prev.timestamp)

    old_difficulty = uint64(prev_b.weight - blocks.block_record(prev_b.prev_hash).weight)

    # Terms are rearranged so there is only one division.
    new_difficulty_precise = (
        (last_block_curr.weight - last_block_prev.weight)
        * constants.SUB_SLOT_TIME_TARGET
        // (constants.SLOT_BLOCKS_TARGET * actual_epoch_time)
    )
    # Take only DIFFICULTY_SIGNIFICANT_BITS significant bits
    new_difficulty = uint64(truncate_to_significant_bits(new_difficulty_precise, constants.SIGNIFICANT_BITS))
    assert count_significant_bits(new_difficulty) <= constants.SIGNIFICANT_BITS

    # Only change by a max factor, to prevent attacks, as in greenpaper, and must be at least 1
    max_diff = uint64(
        truncate_to_significant_bits(
            constants.DIFFICULTY_CHANGE_MAX_FACTOR * old_difficulty,
            constants.SIGNIFICANT_BITS,
        )
    )
    min_diff = uint64(
        truncate_to_significant_bits(
            old_difficulty // constants.DIFFICULTY_CHANGE_MAX_FACTOR,
            constants.SIGNIFICANT_BITS,
        )
    )
    if new_difficulty >= old_difficulty:
        return min(new_difficulty, max_diff)
    else:
        return max([uint64(1), new_difficulty, min_diff])


def get_sub_slot_iters_and_difficulty(
    constants: ConsensusConstants,
    header_block: Union[UnfinishedHeaderBlock, UnfinishedBlock, HeaderBlock, FullBlock],
    prev_b: Optional[BlockRecord],
    blocks: BlockchainInterface,
) -> Tuple[uint64, uint64]:
    """
    Retrieves the current sub_slot iters and difficulty of the block header_block. Note, this is the current
    difficulty, not the next one.

    Args:
        constants: consensus constants being used for this chain
        header_block: the current block
        prev_b: the previous block before header_block
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

    sp_total_iters = prev_b.sp_total_iters(constants)
    difficulty: uint64 = get_next_difficulty(
        constants,
        blocks,
        prev_b.prev_hash,
        prev_b.height,
        prev_difficulty,
        prev_b.deficit,
        len(header_block.finished_sub_slots) > 0,
        sp_total_iters,
    )

    sub_slot_iters: uint64 = get_next_sub_slot_iters(
        constants,
        blocks,
        prev_b.prev_hash,
        prev_b.height,
        prev_b.sub_slot_iters,
        prev_b.deficit,
        len(header_block.finished_sub_slots) > 0,
        sp_total_iters,
    )

    return sub_slot_iters, difficulty
