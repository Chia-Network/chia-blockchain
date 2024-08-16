from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from chia_rs import ClassgroupElement

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.difficulty_adjustment import can_finish_sub_and_full_epoch
from chia.consensus.get_block_challenge import final_eos_is_already_included, get_block_challenge
from chia.consensus.pot_iterations import is_overflow_block
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.util.ints import uint64


@dataclass
class SubSlotState:
    icc_challenge_hash: Optional[bytes32] = None
    icc_iters_committed: Optional[uint64] = None
    icc_iters_proof: Optional[uint64] = None
    icc_vdf_input: Optional[ClassgroupElement] = None


# In order to validate a block we may need information from previous blocks.
# This class holds all previous block records that we may need, and makes block
# validation self-contained
@dataclass
class PrevChainState:
    # the previous block, or None if we're at genesis
    prev_b: Optional[BlockRecord]
    # the previous *transaction* block
    prev_tx_block: Optional[BlockRecord]
    # the timestamp of the previous transaction block
    prev_tx_timestamp: Optional[uint64]
    # the number of blocks since the start of the current sub slot
    num_blocks: int
    # the first block in the subslot
    first_in_subslot: Optional[BlockRecord]
    # sub slot state for each finished sub slot in the block
    sub_slot_state: List[SubSlotState]

    final_eos_is_already_included: bool
    # block challenge (or genesis challenge if height 0)
    challenge: bytes32
    can_finish_se: bool
    can_finish_epoch: bool


def find_chain_state(
    blocks: BlockchainInterface,
    header_block: UnfinishedHeaderBlock,
    expected_sub_slot_iters: uint64,
    skip_overflow_last_ss_validation: bool,
    constants: ConsensusConstants,
) -> PrevChainState:

    prev_b = blocks.try_block_record(header_block.prev_header_hash)
    sub_slot_state: List[SubSlotState] = []

    for finished_sub_slot_n in range(len(header_block.finished_sub_slots)):
        icc_challenge_hash: Optional[bytes32] = None
        icc_iters_committed: Optional[uint64] = None
        icc_iters_proof: Optional[uint64] = None
        icc_vdf_input: Optional[ClassgroupElement] = None
        if prev_b is not None and prev_b.deficit < constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
            # There should be no ICC chain if the last block's deficit is 16
            # Prev sb's deficit is 0, 1, 2, 3, or 4
            if finished_sub_slot_n == 0:
                # This is the first sub slot after the last sb, which must have deficit 1-4, and thus an ICC
                curr = prev_b
                while not curr.is_challenge_block(constants) and not curr.first_in_sub_slot:
                    curr = blocks.block_record(curr.prev_hash)
                if curr.is_challenge_block(constants):
                    icc_challenge_hash = curr.challenge_block_info_hash
                    icc_iters_committed = uint64(prev_b.sub_slot_iters - curr.ip_iters(constants))
                else:
                    assert curr.finished_infused_challenge_slot_hashes is not None
                    icc_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
                    icc_iters_committed = prev_b.sub_slot_iters
                icc_iters_proof = uint64(prev_b.sub_slot_iters - prev_b.ip_iters(constants))
                if prev_b.is_challenge_block(constants):
                    icc_vdf_input = ClassgroupElement.get_default_element()
                else:
                    icc_vdf_input = prev_b.infused_challenge_vdf_output
            else:
                # This is not the first sub slot after the last block, so we might not have an ICC
                if (
                    header_block.finished_sub_slots[finished_sub_slot_n - 1].reward_chain.deficit
                    < constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
                ):
                    finished_ss = header_block.finished_sub_slots[finished_sub_slot_n - 1]
                    assert finished_ss.infused_challenge_chain is not None

                    # Only sets the icc iff the previous sub slots deficit is 4 or less
                    icc_challenge_hash = finished_ss.infused_challenge_chain.get_hash()
                    icc_iters_committed = prev_b.sub_slot_iters
                    icc_iters_proof = icc_iters_committed
                    icc_vdf_input = ClassgroupElement.get_default_element()

        sub_slot_state.append(
            SubSlotState(
                icc_challenge_hash,
                icc_iters_committed,
                icc_iters_proof,
                icc_vdf_input,
            )
        )

    first_in_subslot: Optional[BlockRecord] = None
    num_blocks = 0
    if prev_b is not None:
        num_blocks = 2  # This includes the current block and the prev block
        curr = prev_b
        while not curr.first_in_sub_slot and curr.height != 0:
            num_blocks += 1
            curr = blocks.block_record(curr.prev_hash)
        assert curr.finished_challenge_slot_hashes is not None
        first_in_subslot = curr

    prev_tx_block: Optional[BlockRecord] = None
    prev_tx_timestamp: Optional[uint64] = None
    if prev_b is not None:
        curr = prev_b
        while not curr.is_transaction_block:
            curr = blocks.block_record(curr.prev_hash)
        prev_tx_block = curr
        prev_tx_timestamp = curr.timestamp

    overflow = is_overflow_block(constants, header_block.reward_chain_block.signage_point_index)

    final_eos_included: bool = False
    can_finish_se: bool = False
    can_finish_epoch: bool = False

    if prev_b is not None:
        final_eos_included = final_eos_is_already_included(header_block, blocks, expected_sub_slot_iters)

    if skip_overflow_last_ss_validation and overflow:
        if final_eos_included:
            skip_overflow_last_ss_validation = False
            finished_sub_slots_since_prev = len(header_block.finished_sub_slots)
        else:
            finished_sub_slots_since_prev = len(header_block.finished_sub_slots) + 1
    else:
        finished_sub_slots_since_prev = len(header_block.finished_sub_slots)

    new_sub_slot: bool = finished_sub_slots_since_prev > 0
    if prev_b is not None and new_sub_slot:
        can_finish_se, can_finish_epoch = can_finish_sub_and_full_epoch(
            constants,
            blocks,
            prev_b.height,
            prev_b.prev_hash,
            prev_b.deficit,
            prev_b.sub_epoch_summary_included is not None,
        )

    challenge: bytes32 = get_block_challenge(
        constants,
        header_block,
        blocks,
        prev_b is None,
        overflow,
        skip_overflow_last_ss_validation,
    )

    return PrevChainState(
        prev_b,
        prev_tx_block,
        prev_tx_timestamp,
        num_blocks,
        first_in_subslot,
        sub_slot_state,
        final_eos_included,
        challenge,
        can_finish_se,
        can_finish_epoch,
    )
