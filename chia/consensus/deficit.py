from typing import Optional

from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.util.ints import uint8, uint32


def calculate_deficit(
    constants: ConsensusConstants,
    height: uint32,
    prev_b: Optional[BlockRecord],
    overflow: bool,
    num_finished_sub_slots: int,
) -> uint8:
    """
    Returns the deficit of the block to be created at height.

    Args:
        constants: consensus constants being used for this chain
        height: block height of the block that we care about
        prev_b: previous block
        overflow: whether or not this is an overflow block
        num_finished_sub_slots: the number of finished slots between infusion points of prev and current
    """
    if height == 0:
        return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1)
    else:
        assert prev_b is not None
        prev_deficit: uint8 = prev_b.deficit
        if prev_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
            # Prev sb must be an overflow sb. However maybe it's in a different sub-slot
            if overflow:
                if num_finished_sub_slots > 0:
                    # We are an overflow block, but in a new sub-slot, so we can decrease the deficit
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
                    return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK)
                else:
                    return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1)
            else:
                # More than one finished sub slot, we can decrease deficit
                return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1)
        else:
            return uint8(prev_deficit - 1)
