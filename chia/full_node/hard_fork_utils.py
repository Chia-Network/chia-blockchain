# Returns the previous transaction block up to the blocks signage point
# we use this for block validation since when the block is farmed we do not know the latest transaction block
# since a new one might be infused by the time the block is infused
from __future__ import annotations

from chia_rs import ConsensusConstants, FullBlock, get_flags_for_height_and_constants

from chia.consensus.blockchain_interface import BlocksProtocol
from chia.consensus.pot_iterations import is_overflow_block


async def get_flags(
    constants: ConsensusConstants,
    blocks: BlocksProtocol,
    block: FullBlock,
) -> int:
    if block.height < constants.HARD_FORK2_HEIGHT:
        return get_flags_for_height_and_constants(block.height, constants)
    if block.height >= constants.HARD_FORK2_HEIGHT + constants.SUB_EPOCH_BLOCKS:
        return get_flags_for_height_and_constants(block.height, constants)

    if block.prev_header_hash == constants.GENESIS_CHALLENGE:
        return get_flags_for_height_and_constants(0, constants)

    sp_index = block.reward_chain_block.signage_point_index
    # For overflow blocks, the SP is in the previous sub-slot, so we need to cross
    # one extra slot boundary before we're past the SP's slot
    overflow = is_overflow_block(constants, sp_index)
    slots_crossed = len(block.finished_sub_slots)
    curr = await blocks.get_block_record_from_db(block.prev_header_hash)
    assert curr is not None
    while curr.height > 0:
        if not overflow:
            before_sp = curr.signage_point_index < sp_index or slots_crossed > 0
        else:
            before_sp = slots_crossed >= 2 or (slots_crossed == 1 and curr.signage_point_index < sp_index)

        if curr.is_transaction_block and before_sp:
            break
        if curr.first_in_sub_slot:
            slots_crossed += 1
        curr = await blocks.get_block_record_from_db(curr.prev_hash)
        assert curr is not None
    return get_flags_for_height_and_constants(curr.height, constants)
