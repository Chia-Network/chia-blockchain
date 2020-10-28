from typing import Dict

from src.full_node.sub_block_record import SubBlockRecord
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32


def sub_block_makes_challenge_block(
    sub_blocks: Dict[bytes32, SubBlockRecord], header_block: HeaderBlock, overflow: bool
) -> bool:
    # Can only make a challenge block if deficit is zero AND (not overflow or not prev_slot_non_overflow_infusions)
    if header_block.height == 0:
        return True
    else:
        prev_sb = sub_blocks[header_block.prev_header_hash]
        if header_block.finished_slots is not None:  # New slot
            deficit = header_block.finished_slots[-1][1].deficit
            prev_slot_non_overflow_infusions = header_block.finished_slots[-1][1].made_non_overflow_infusions
        else:
            curr: SubBlockRecord = prev_sb
            while not curr.first_in_slot:
                curr = sub_blocks[curr.prev_hash]
            deficit = curr.deficit
            prev_slot_non_overflow_infusions = curr.previous_slot_non_overflow_infusions
        return deficit == 0 and (not overflow or not prev_slot_non_overflow_infusions)
