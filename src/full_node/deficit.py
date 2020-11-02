from typing import Optional

from src.consensus.constants import ConsensusConstants
from src.full_node.sub_block_record import SubBlockRecord
from src.util.ints import uint32, uint8


def calculate_deficit(
    constants: ConsensusConstants,
    height: uint32,
    prev_sb: Optional[SubBlockRecord],
    overflow: bool,
    passed_slot_barrier: bool,
) -> uint8:
    if height == 0:
        return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK) - 1
    else:
        prev_deficit: uint8 = prev_sb.deficit
        if prev_deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
            # Prev sb must be an overflow sb
            if overflow and not passed_slot_barrier:
                # Still overflowed, so we cannot decrease the deficit
                return uint8(prev_deficit)
            else:
                # We have passed the first overflow, can decrease
                return uint8(prev_deficit - 1)
        elif prev_deficit == 0:
            if passed_slot_barrier:
                return uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK)
            else:
                return uint8(0)
        else:
            return uint8(prev_deficit - 1)
