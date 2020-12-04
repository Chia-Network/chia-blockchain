from typing import Optional

from src.consensus.constants import ConsensusConstants
from src.consensus.sub_block_record import SubBlockRecord
from src.util.ints import uint32, uint8


def calculate_deficit(
    constants: ConsensusConstants,
    sub_block_height: uint32,
    prev_sb: Optional[SubBlockRecord],
    overflow: bool,
    passed_slot_barrier: bool,
) -> uint8:
    if sub_block_height == 0:
        return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK) - 1
    else:
        prev_deficit: uint8 = prev_sb.deficit
        if prev_deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
            # Prev sb must be an overflow sb
            if overflow:
                # Still overflowed, so we cannot decrease the deficit
                return uint8(prev_deficit)
            else:
                # We are no longer overflow, can decrease
                return uint8(prev_deficit - 1)
        elif prev_deficit == 0:
            if passed_slot_barrier:
                if overflow:
                    return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK)
                else:
                    return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1)
            else:
                return uint8(0)
        else:
            return uint8(prev_deficit - 1)
