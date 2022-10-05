from __future__ import annotations

import logging
from typing import List, Union

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.util.ints import uint64

log = logging.getLogger(__name__)


def final_eos_is_already_included(
    header_block: Union[UnfinishedHeaderBlock, UnfinishedBlock, HeaderBlock, FullBlock],
    blocks: BlockchainInterface,
    sub_slot_iters: uint64,
) -> bool:
    """
    Args:
        header_block: An overflow block, with potentially missing information about the new sub slot
        blocks: all blocks that have been included before header_block
        sub_slot_iters: sub_slot_iters at the header_block

    Returns: True iff the missing sub slot was already included in a previous block. Returns False if the sub
    slot was not included yet, and therefore it is the responsibility of this block to include it

    """
    if len(header_block.finished_sub_slots) > 0:
        # We already have an included empty sub slot, which means the prev block is 2 sub slots behind.
        return False
    curr: BlockRecord = blocks.block_record(header_block.prev_header_hash)

    # We also check if curr is close to header_block, which means it's in the same sub slot
    seen_overflow_block = curr.overflow and (header_block.total_iters - curr.total_iters < sub_slot_iters // 2)
    while not curr.first_in_sub_slot and not curr.height == 0:
        if curr.overflow and header_block.total_iters - curr.total_iters < sub_slot_iters // 2:
            seen_overflow_block = True
        curr = blocks.block_record(curr.prev_hash)

    if curr.first_in_sub_slot and seen_overflow_block:
        # We have seen another overflow block in this slot (same as header_block), therefore there are no
        # missing sub slots
        return True

    # We have not seen any overflow blocks, therefore header_block will have to include the missing sub slot in
    # the future
    return False


def get_block_challenge(
    constants: ConsensusConstants,
    header_block: Union[UnfinishedHeaderBlock, UnfinishedBlock, HeaderBlock, FullBlock],
    blocks: BlockchainInterface,
    genesis_block: bool,
    overflow: bool,
    skip_overflow_last_ss_validation: bool,
) -> bytes32:
    if len(header_block.finished_sub_slots) > 0:
        if overflow:
            # New sub-slot with overflow block
            if skip_overflow_last_ss_validation:
                # In this case, we are missing the final sub-slot bundle (it's not finished yet), however
                # There is a whole empty slot before this block is infused
                challenge: bytes32 = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
            else:
                challenge = header_block.finished_sub_slots[
                    -1
                ].challenge_chain.challenge_chain_end_of_slot_vdf.challenge
        else:
            # No overflow, new slot with a new challenge
            challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
    else:
        if genesis_block:
            challenge = constants.GENESIS_CHALLENGE
        else:
            if overflow:
                if skip_overflow_last_ss_validation:
                    # Overflow infusion without the new slot, so get the last challenge
                    challenges_to_look_for = 1
                else:
                    # Overflow infusion, so get the second to last challenge. skip_overflow_last_ss_validation is False,
                    # Which means no sub slots are omitted
                    challenges_to_look_for = 2
            else:
                challenges_to_look_for = 1
            reversed_challenge_hashes: List[bytes32] = []
            curr: BlockRecord = blocks.block_record(header_block.prev_header_hash)
            while len(reversed_challenge_hashes) < challenges_to_look_for:
                if curr.first_in_sub_slot:
                    assert curr.finished_challenge_slot_hashes is not None
                    reversed_challenge_hashes += reversed(curr.finished_challenge_slot_hashes)
                if curr.height == 0:
                    assert curr.finished_challenge_slot_hashes is not None
                    assert len(curr.finished_challenge_slot_hashes) > 0
                    break
                curr = blocks.block_record(curr.prev_hash)
            challenge = reversed_challenge_hashes[challenges_to_look_for - 1]
    return challenge
