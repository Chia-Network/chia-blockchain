from __future__ import annotations

import logging

from chia_rs import BlockRecord, ConsensusConstants, FullBlock, HeaderBlock, UnfinishedBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.pot_iterations import is_overflow_block
from chia.types.blockchain_format.proof_of_space import FILTER_WINDOW_SIZE
from chia.types.unfinished_header_block import UnfinishedHeaderBlock

log = logging.getLogger(__name__)


def final_eos_is_already_included(
    header_block: UnfinishedHeaderBlock | UnfinishedBlock | HeaderBlock | FullBlock,
    blocks: BlockRecordsProtocol,
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
    header_block: UnfinishedHeaderBlock | UnfinishedBlock | HeaderBlock | FullBlock,
    blocks: BlockRecordsProtocol,
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
    elif genesis_block:
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
        reversed_challenge_hashes: list[bytes32] = []
        curr: BlockRecord = blocks.block_record(header_block.prev_header_hash)
        while len(reversed_challenge_hashes) < challenges_to_look_for:
            if curr.first_in_sub_slot:
                assert curr.finished_challenge_slot_hashes is not None
                reversed_challenge_hashes += reversed(curr.finished_challenge_slot_hashes)
                if len(reversed_challenge_hashes) >= challenges_to_look_for:
                    break
            if curr.height == 0:
                assert curr.finished_challenge_slot_hashes is not None
                assert len(curr.finished_challenge_slot_hashes) > 0
                break
            curr = blocks.block_record(curr.prev_hash)
        challenge = reversed_challenge_hashes[challenges_to_look_for - 1]
    return challenge


# Returns the latest transaction block infused before the provided signage point index.
# we use this for block validation since when the block is farmed we do not know the latest transaction block
# since a new one might be infused by the time the block is infused
def pre_sp_tx_block(
    constants: ConsensusConstants,
    blocks: BlockRecordsProtocol,
    *,
    prev_b_hash: bytes32,
    sp_index: uint8,
    finished_sub_slots: int,
) -> BlockRecord | None:
    if prev_b_hash == constants.GENESIS_CHALLENGE:
        return None
    curr = blocks.block_record(prev_b_hash)
    overflow = is_overflow_block(constants, sp_index)
    slots_crossed = finished_sub_slots
    while curr.height > 0:
        if curr.is_transaction_block and is_infused_before_sp(
            constants,
            curr.signage_point_index,
            sp_index,
            slots_crossed,
            overflow,
        ):
            break
        if curr.first_in_sub_slot:
            slots_crossed += 1
        curr = blocks.block_record(curr.prev_hash)
    return curr


def is_infused_before_sp(
    constants: ConsensusConstants,
    candidate_sp_index: uint8,
    sp_index: uint8,
    slots_crossed_at_ip: int,
    overflow: bool,
) -> bool:
    candidate_overflow = is_overflow_block(constants, candidate_sp_index)
    # The walker counts whole slots between infusion points. This comparison is against the checked SP, so
    # overflow blocks need one-slot adjustments because their SP is in the slot before their IP.
    actual_slots_crossed_at_ip = slots_crossed_at_ip
    if candidate_overflow:
        actual_slots_crossed_at_ip += 1
    if overflow:
        actual_slots_crossed_at_ip -= 1

    # Distance in SP intervals. If slots were crossed, a smaller checked SP index can still be after a larger
    # candidate SP index, so add a full slot width for each crossed slot.
    sp_intervals_until_current_sp = (
        sp_index - candidate_sp_index + actual_slots_crossed_at_ip * constants.NUM_SPS_SUB_SLOT
    )
    return sp_intervals_until_current_sp > constants.NUM_SP_INTERVALS_EXTRA


def pre_sp_tx_block_height(
    constants: ConsensusConstants,
    blocks: BlockRecordsProtocol,
    *,
    prev_b_hash: bytes32,
    sp_index: uint8,
    finished_sub_slots: int,
) -> uint32:
    latest_tx_block = pre_sp_tx_block(
        constants=constants,
        blocks=blocks,
        prev_b_hash=prev_b_hash,
        sp_index=sp_index,
        finished_sub_slots=finished_sub_slots,
    )
    if latest_tx_block is None:
        return uint32(0)
    return latest_tx_block.height


def get_filter_challenge_from_chain(
    constants: ConsensusConstants,
    blocks: BlockRecordsProtocol,
    header_block: UnfinishedHeaderBlock | HeaderBlock | FullBlock,
    current_challenge: bytes32,
    signage_point_index: int,
) -> bytes32 | None:
    """Derive filter_challenge for V2 plot filter from chain data.

    Returns the cc sub-slot challenge hash of a previously completed sub-slot
    """
    sub_slots_back = 2 if signage_point_index < FILTER_WINDOW_SIZE else 1

    # Collect sub-slot challenge hashes newest-first
    reversed_challenges: list[bytes32] = []

    for fss in reversed(header_block.finished_sub_slots):
        reversed_challenges.append(fss.challenge_chain.get_hash())

    reached_genesis = header_block.prev_header_hash == constants.GENESIS_CHALLENGE
    if not reached_genesis:
        curr = blocks.block_record(header_block.prev_header_hash)
        while True:
            if curr.first_in_sub_slot:
                assert curr.finished_challenge_slot_hashes is not None
                for ch in reversed(curr.finished_challenge_slot_hashes):
                    reversed_challenges.append(ch)
            if curr.height == 0:
                reached_genesis = True
                break
            if len(reversed_challenges) > sub_slots_back + 3:
                break
            curr = blocks.block_record(curr.prev_hash)

    if reached_genesis and constants.GENESIS_CHALLENGE not in reversed_challenges:
        reversed_challenges.append(constants.GENESIS_CHALLENGE)

    try:
        idx = reversed_challenges.index(current_challenge)
    except ValueError:
        return None

    target_idx = idx + sub_slots_back
    if target_idx >= len(reversed_challenges):
        return None

    return reversed_challenges[target_idx]


def post_hard_fork2(
    constants: ConsensusConstants,
    blocks: BlockRecordsProtocol,
    *,
    prev_b_hash: bytes32,
    sp_index: uint8,
    finished_sub_slots: int,
) -> bool:
    prev_b = blocks.try_block_record(prev_b_hash)
    if prev_b is None:
        assert prev_b_hash == constants.GENESIS_CHALLENGE
        return uint32(0) == constants.HARD_FORK2_HEIGHT

    candidate_height = prev_b.height + 1
    if candidate_height < constants.HARD_FORK2_HEIGHT:
        return False
    if candidate_height >= constants.HARD_FORK2_HEIGHT + constants.SUB_EPOCH_BLOCKS:
        return True

    return (
        pre_sp_tx_block_height(
            constants=constants,
            blocks=blocks,
            prev_b_hash=prev_b_hash,
            sp_index=sp_index,
            finished_sub_slots=finished_sub_slots,
        )
        >= constants.HARD_FORK2_HEIGHT
    )
