from typing import Optional

from src.consensus.constants import ConsensusConstants
from src.consensus.sub_block_record import SubBlockRecord
from src.util.ints import uint32, uint8


def calculate_deficit(
    constants: ConsensusConstants,
    sub_block_height: uint32,
    prev_sb: Optional[SubBlockRecord],
    overflow: bool,
    num_finished_sub_slots: int,
) -> uint8:
    """
    Returns the deficit of the sub-block to be created at sub_block_height.

    Args:
        constants: consensus constants being used for this chain
        sub_block_height: sub-block height of the block that we care about
        prev_sb: previous sub-block
        overflow: whether or not this is an overflow sub-block
        num_finished_sub_slots: the number of finished slots between infusion points of prev and current
    """
    if sub_block_height == 0:
        return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1)
    else:
        assert prev_sb is not None
        prev_deficit: uint8 = prev_sb.deficit
        if prev_deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
            # Prev sb must be an overflow sb. However maybe it's in a different sub-slot
            if overflow:
                if num_finished_sub_slots > 0:
                    # We are an overflow sub-block, but in a new sub-slot, so we can decrease the deficit
                    return uint8(prev_deficit - 1)
                # Still overflowed, so we cannot decrease the deficit
                return uint8(prev_deficit)
            else:
                # We are no longer overflow, can decrease
                return uint8(prev_deficit - 1)
        elif prev_deficit == 0:
            if num_finished_sub_slots == 0:
                return uint8(0)
            elif num_finished_sub_slots == 1:
                if overflow:
                    return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK)
                else:
                    return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1)
            else:
                # More than one finished sub slot, we can decrease deficit
                return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1)
        else:
            return uint8(prev_deficit - 1)
