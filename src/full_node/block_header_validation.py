import dataclasses
import logging
from typing import Dict, Optional, List, Tuple
import time

from blspy import AugSchemeMPL

from src.consensus.constants import ConsensusConstants
from src.full_node.deficit import calculate_deficit
from src.types.sized_bytes import bytes32
from src.util.errors import Err
from src.util.ints import uint32, uint64, uint128
from src.types.unfinished_header_block import UnfinishedHeaderBlock
from src.types.header_block import HeaderBlock
from src.full_node.sub_block_record import SubBlockRecord
from src.full_node.difficulty_adjustment import get_next_ips, get_next_difficulty
from src.types.vdf import VDFInfo
from src.consensus.pot_iterations import (
    is_overflow_sub_block,
    calculate_ip_iters,
    calculate_sp_iters,
    calculate_slot_iters,
    calculate_iterations_quality,
)
from src.full_node.difficulty_adjustment import finishes_sub_epoch
from src.util.hash import std_hash
from src.types.classgroup import ClassgroupElement
from src.types.sub_epoch_summary import SubEpochSummary

log = logging.getLogger(__name__)


# noinspection PyCallByClass
async def validate_unfinished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: UnfinishedHeaderBlock,
    check_filter: bool,
) -> Tuple[Optional[uint64], Optional[Err]]:
    """
    Validates an unfinished header block. This is a block without the infusion VDFs (unfinished)
    and without transactions and transaction info (header). Returns (required_iters, error).
    """
    # 1. Check that the previous block exists in the blockchain

    new_slot: bool = len(header_block.finished_sub_slots) > 0
    if header_block.height == 0:
        prev_sb: Optional[SubBlockRecord] = None
        finishes_se = False
        finishes_epoch = False
        difficulty: uint64 = uint64(constants.DIFFICULTY_STARTING)
        ips: uint64 = uint64(constants.IPS_STARTING)
    else:
        prev_sb: Optional[SubBlockRecord] = sub_blocks[header_block.prev_header_hash]
        if prev_sb is None:
            return None, Err.DOES_NOT_EXTEND

        # If the previous sub block finishes a sub-epoch, that means that this sub-block should have an updated diff
        finishes_se = finishes_sub_epoch(constants, prev_sb.height, prev_sb.deficit, False)
        finishes_epoch: bool = finishes_sub_epoch(constants, prev_sb.height, prev_sb.deficit, True)

        difficulty: uint64 = get_next_difficulty(
            constants,
            sub_blocks,
            height_to_hash,
            header_block.prev_header_hash,
            prev_sb.height,
            prev_sb.deficit,
            uint64(prev_sb.weight - sub_blocks[prev_sb.prev_hash].weight),
            new_slot,
            prev_sb.total_iters,
        )
        ips: uint64 = get_next_ips(
            constants,
            sub_blocks,
            height_to_hash,
            header_block.prev_header_hash,
            prev_sb.height,
            prev_sb.deficit,
            prev_sb.ips,
            new_slot,
            prev_sb.total_iters,
        )

    # 2. Check finished slots that have been crossed since prev_sb
    ses_hash: Optional[bytes32] = None
    if new_slot:
        # Finished a slot(s) since previous block. The first sub-slot must have at least one sub-block, and all
        # subsequent sub-slots must be empty
        for finished_sub_slot_n, sub_slot in enumerate(header_block.finished_sub_slots):
            # Start of slot challenge is fetched from ICP
            challenge_hash: bytes32 = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge_hash

            # 2a. check sub-slot challenge hash
            if finished_sub_slot_n == 0:
                if prev_sb is None:
                    if challenge_hash != constants.FIRST_CC_CHALLENGE:
                        return None, Err.INVALID_PREV_CHALLENGE_SLOT_HASH
                else:
                    curr: SubBlockRecord = prev_sb
                    while not curr.first_in_slot:
                        curr = sub_blocks[curr.prev_hash]
                    if not curr.finished_challenge_slot_hashes[-1] != challenge_hash:
                        return None, Err.INVALID_PREV_CHALLENGE_SLOT_HASH
            else:
                if (
                    not header_block.finished_sub_slots[finished_sub_slot_n - 1].challenge_chain.get_hash()
                    == challenge_hash
                ):
                    return None, Err.INVALID_PREV_CHALLENGE_SLOT_HASH

            # 2b. Validate the infusion challenge chain VDF
            if prev_sb is None:
                if sub_slot.infused_challenge_chain is not None:
                    return None, Err.SHOULD_NOT_HAVE_ICC
            else:
                curr: SubBlockRecord = prev_sb
                icc_iters_committed: Optional[uint64] = None
                icc_iters_proof: Optional[uint64] = None
                if curr.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    icc_challenge_hash: Optional[bytes32] = None
                else:
                    if finished_sub_slot_n == 0:
                        while (
                            curr.deficit < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1 and not curr.first_in_slot
                        ):
                            curr = sub_blocks[curr.prev_hash]
                        if curr.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                            icc_challenge_hash = curr.challenge_block_info_hash
                            ip_iters_prev = calculate_ip_iters(constants, prev_sb.ips, prev_sb.required_iters)
                            ip_iters_challenge_block = calculate_ip_iters(constants, curr.ips, curr.required_iters)
                            icc_iters_proof: uint64 = calculate_slot_iters(constants, prev_sb.ips) - ip_iters_prev
                            icc_iters_committed: uint64 = (
                                calculate_slot_iters(constants, prev_sb.ips) - ip_iters_challenge_block
                            )

                        else:
                            icc_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
                            icc_iters_committed = calculate_slot_iters(constants, prev_sb.ips)
                            icc_iters_proof = icc_iters_committed
                    else:
                        icc_challenge_hash = header_block.finished_sub_slots[
                            finished_sub_slot_n - 1
                        ].infused_challenge_chain.get_hash()
                        icc_iters_committed = calculate_slot_iters(constants, prev_sb.ips)
                        icc_iters_proof = icc_iters_committed

                assert (sub_slot.infused_challenge_chain is None) == (icc_challenge_hash is None)
                if sub_slot.infused_challenge_chain is not None:
                    print("2c")
                    # 2c. Check infused challenge chain sub-slot VDF
                    # Only validate from prev_sb to optimize
                    target_vdf_info = VDFInfo(
                        icc_challenge_hash,
                        prev_sb.infused_challenge_vdf_output,
                        icc_iters_proof,
                        sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output,
                    )
                    if sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf != dataclasses.replace(
                        target_vdf_info,
                        input=ClassgroupElement.get_default_element(),
                        number_of_iterations=icc_iters_committed,
                    ):
                        return None, Err.INVALID_ICC_VDF
                    if not sub_slot.proofs.challenge_chain_slot_proof.is_valid(constants, target_vdf_info, None):
                        return None, Err.INVALID_ICC_VDF

                    # 2d. Check infused challenge sub-slot hash in challenge sub-slot
                    if sub_slot.reward_chain.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        if (
                            sub_slot.infused_challenge_chain.get_hash()
                            != sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash
                        ):
                            return None, Err.INVALID_ICC_HASH_CC
                    else:
                        if sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash is not None:
                            return None, Err.INVALID_ICC_HASH_CC

                    # 2e. Check infused challenge sub-slot hash in reward sub-slot
                    if (
                        sub_slot.infused_challenge_chain.get_hash()
                        != sub_slot.reward_chain.infused_challenge_chain_sub_slot_hash
                    ):
                        return None, Err.INVALID_ICC_HASH_RC
                else:
                    assert sub_slot.infused_challenge_chain is None
                    if sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash is not None:
                        return None, Err.INVALID_ICC_HASH_CC
                    if sub_slot.reward_chain.infused_challenge_chain_sub_slot_hash is not None:
                        return None, Err.INVALID_ICC_HASH_RC

            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                assert ses_hash is None  # Only one of the slots can have it
                ses_hash = sub_slot.challenge_chain.subepoch_summary_hash

            # 2f. check sub-epoch summary hash is None for empty slots
            if finished_sub_slot_n != 0:
                if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                    return None, Err.INVALID_SUB_EPOCH_SUMMARY_HASH

            # 2g. Check new difficulty
            if finishes_epoch:
                if sub_slot.challenge_chain.new_ips != ips:
                    return None, Err.INVALID_NEW_IPS
                if sub_slot.challenge_chain.new_difficulty != difficulty:
                    return None, Err.INVALID_NEW_DIFFICULTY
            else:
                if sub_slot.challenge_chain.new_ips is not None:
                    return None, Err.INVALID_NEW_IPS
                if sub_slot.challenge_chain.new_difficulty is not None:
                    return None, Err.INVALID_NEW_DIFFICULTY

            # 2h. Check challenge sub-slot hash in reward sub-slot
            if sub_slot.challenge_chain.get_hash() != sub_slot.reward_chain.challenge_chain_sub_slot_hash:
                return None, Err.INVALID_CHALLENGE_SLOT_HASH_RC

            # 2i. Check challenge chain sub-slot VDF
            # 2j. Check end of reward slot VDF
            slot_iters = calculate_slot_iters(constants, ips)
            eos_vdf_iters: uint64 = slot_iters
            cc_start_element: ClassgroupElement = ClassgroupElement.get_default_element()
            cc_eos_vdf_challenge: bytes32 = challenge_hash
            if prev_sb is None:
                if finished_sub_slot_n == 0:
                    # First block, one empty slot. prior_point is the initial challenge
                    rc_eos_vdf_challenge: bytes32 = constants.FIRST_RC_CHALLENGE
                    cc_eos_vdf_challenge: bytes32 = constants.FIRST_CC_CHALLENGE
                else:
                    # First block, but have at least two empty slots
                    rc_eos_vdf_challenge: bytes32 = header_block.finished_sub_slots[
                        finished_sub_slot_n - 1
                    ].reward_chain.get_hash()
            else:
                if finished_sub_slot_n == 0:
                    # No empty slots, so the starting point of VDF is the last reward block. Uses
                    # the same IPS as the previous block, since it's the same slot
                    rc_eos_vdf_challenge: bytes32 = prev_sb.reward_infusion_output
                    slot_iters = calculate_slot_iters(constants, prev_sb.ips)
                    eos_vdf_iters = slot_iters - calculate_ip_iters(constants, prev_sb.ips, prev_sb.required_iters)
                    cc_start_element: ClassgroupElement = prev_sb.challenge_vdf_output
                else:
                    # At least one empty slot, so use previous slot hash. IPS might change because it's a new slot
                    rc_eos_vdf_challenge: bytes32 = header_block.finished_sub_slots[
                        finished_sub_slot_n - 1
                    ].reward_chain.get_hash()

            target_vdf_info = VDFInfo(
                rc_eos_vdf_challenge,
                ClassgroupElement.get_default_element(),  # Reward chain always infuses at previous sub-block
                eos_vdf_iters,
                sub_slot.reward_chain.end_of_slot_vdf.output,
            )
            if not sub_slot.proofs.reward_chain_slot_proof.is_valid(
                constants, sub_slot.reward_chain.end_of_slot_vdf, target_vdf_info
            ):
                return None, Err.INVALID_RC_EOS_VDF

            partial_cc_vdf_info = VDFInfo(
                cc_eos_vdf_challenge,
                cc_start_element,
                eos_vdf_iters,
                sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output,
            )
            # Check that the modified data is correct
            if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf != dataclasses.replace(
                partial_cc_vdf_info, input=ClassgroupElement.get_default_element(), number_of_iterations=slot_iters
            ):
                return None, Err.INVALID_CC_EOS_VDF

            # Pass in None for target info since we are only checking the proof from the temporary point,
            # but the challenge_chain_end_of_slot_vdf actually starts from the start of slot (for light clients)
            if not sub_slot.proofs.challenge_chain_slot_proof.is_valid(constants, partial_cc_vdf_info, None):
                return None, Err.INVALID_CC_EOS_VDF

            # 2k. Check deficit (5 deficit edge case for genesis block)
            if prev_sb is None:
                if sub_slot.reward_chain.deficit != constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    return None, Err.INVALID_DEFICIT
            else:
                if prev_sb.deficit == 0:
                    # If there is a challenge chain infusion, resets deficit to 5
                    if sub_slot.reward_chain.deficit != constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        return None, Err.INVALID_DEFICIT
                else:
                    # Otherwise, deficit stays the same at the slot ends, cannot reset until 0
                    if sub_slot.reward_chain.deficit != prev_sb.deficit:
                        return None, Err.INVALID_DEFICIT

        # 3. Check sub-epoch summary
        # Note that the subepoch summary is the summary of the previous subepoch (not the one that just finished)
        if ses_hash is not None:
            # 3a. Check that genesis block does not have sub-epoch summary
            if prev_sb is None:
                return None, Err.INVALID_SUB_EPOCH_SUMMARY

            # 3b. Check that we finished a slot and we finished a sub-epoch
            if not new_slot or not finishes_se:
                return None, Err.INVALID_SUB_EPOCH_SUMMARY

            curr = prev_sb
            while curr.sub_epoch_summary_included_hash is None:
                curr = sub_blocks[curr.prev_hash]

            # 3c. Check the actual sub-epoch is correct
            expected_sub_epoch_summary = SubEpochSummary(
                curr.sub_epoch_summary_included_hash,
                curr.finished_reward_slot_hashes[0],
                curr.height % constants.SUB_EPOCH_SUB_BLOCKS,
                difficulty if finishes_epoch else None,
                ips if finishes_epoch else None,
            )
            if expected_sub_epoch_summary.get_hash() != ses_hash:
                return None, Err.INVALID_SUB_EPOCH_SUMMARY
        else:
            # 3d. Check that we don't have to include a sub-epoch summary
            if prev_sb is not None and new_slot:
                finishes = finishes_sub_epoch(
                    constants, sub_blocks, header_block.prev_header_hash, False
                )
                if finishes:
                    return None, Err.INVALID_SUB_EPOCH_SUMMARY

    # 4. Check proof of space
    if header_block.reward_chain_sub_block.challenge_chain_sp_vdf is None:
        # Edge case of first sp (start of slot), where sp_iters == 0
        cc_sp_hash: bytes32 = header_block.reward_chain_sub_block.proof_of_space.challenge_hash
    else:
        cc_sp_hash = header_block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash()

    q_str: Optional[bytes32] = header_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
        constants,
        cc_sp_hash,
        header_block.reward_chain_sub_block.challenge_chain_sp_signature,
    )
    if q_str is None:
        return None, Err.INVALID_POSPACE

    # Note that required iters might be from the previous slot (if we are in an overflow sub-block)
    required_iters: uint64 = calculate_iterations_quality(
        q_str,
        header_block.reward_chain_sub_block.proof_of_space.size,
        difficulty,
    )

    sp_iters: uint64 = calculate_sp_iters(constants, ips, required_iters)
    ip_iters: uint64 = calculate_ip_iters(constants, ips, required_iters)
    slot_iters: uint64 = calculate_slot_iters(constants, ips)
    overflow = is_overflow_sub_block(constants, ips, required_iters)

    if header_block.reward_chain_sub_block.challenge_chain_sp_vdf is None:
        # Blocks with very low required iters are not overflow blocks
        assert not overflow

    # 5. Check no overflows in new sub-epoch
    if overflow and ses_hash is not None:
        return None, Err.NO_OVERFLOWS_IN_NEW_SUBEPOCH

    # If sub_block state is correct, we should always find a challenge here
    # This computes what the challenge should be for this sub-block
    if prev_sb is None:
        challenge: bytes32 = constants.FIRST_CC_CHALLENGE
    else:
        if new_slot:
            if overflow:
                if header_block.finished_sub_slots[-1].challenge_chain.proof_of_space is not None:
                    # New slot with overflow block, where prev slot had challenge block
                    challenge = header_block.finished_sub_slots[-1].challenge_chain.proof_of_space.challenge_hash
                else:
                    # New slot with overflow block, where prev slot had no challenge block
                    challenge = header_block.finished_sub_slots[-1].challenge_chain.end_of_slot_vdf.challenge_hash
            else:
                # No overflow, new slot with a new challenge
                challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
        else:
            if overflow:
                # Overflow infusion, so get the second to last challenge
                challenges_to_look_for = 2
            else:
                challenges_to_look_for = 1
            reversed_challenge_hashes: List[bytes32] = []
            curr: SubBlockRecord = prev_sb
            while len(reversed_challenge_hashes) < challenges_to_look_for:
                if curr.first_in_slot:
                    reversed_challenge_hashes += reversed(curr.finished_challenge_slot_hashes)
                curr = sub_blocks[curr.prev_hash]
            challenge = reversed_challenge_hashes[-challenges_to_look_for]
    assert challenge is not None

    # 6. Check challenge in proof of space is valid
    if challenge != header_block.reward_chain_sub_block.proof_of_space.challenge_hash:
        return None, Err.INVALID_POSPACE_CHALLENGE

    if prev_sb is not None:
        # 7. Check sub-block height
        if header_block.height != prev_sb.height + 1:
            return None, Err.INVALID_HEIGHT

        # 8. Check weight
        if header_block.weight != prev_sb.weight + difficulty:
            return None, Err.INVALID_WEIGHT
    else:
        if header_block.weight != constants.DIFFICULTY_STARTING:
            return None, Err.INVALID_WEIGHT

    # 9. Check total iters
    if prev_sb is None:
        total_iters: uint128 = uint128(
            constants.IPS_STARTING * constants.SLOT_TIME_TARGET * len(header_block.finished_sub_slots)
        )
        total_iters += ip_iters
    else:
        prev_sb_iters = calculate_ip_iters(constants, prev_sb.ips, prev_sb.required_iters)
        if new_slot:
            total_iters: uint128 = prev_sb.total_iters
            prev_sb_slot_iters = calculate_slot_iters(constants, prev_sb.ips)
            # Add the rest of the slot of prev_sb
            total_iters += prev_sb_slot_iters - prev_sb_iters
            # Add other empty slots
            total_iters += slot_iters * (len(header_block.finished_slot) - 1)
        else:
            # Slot iters is guaranteed to be the same for header_block and prev_sb
            # This takes the beginning of the slot, and adds ip_iters
            total_iters = uint128(prev_sb.total_iters - prev_sb_iters) + ip_iters
    if total_iters != header_block.reward_chain_sub_block.total_iters:
        return None, Err.INVALID_TOTAL_ITERS

    if new_slot and not overflow:
        # Start from start of this slot. Case of no overflow slots. Also includes genesis block after empty slot(s),
        # but not overflowing
        rc_vdf_challenge: bytes32 = header_block.finished_sub_slots[-1].reward_chain.get_hash()
        sp_vdf_iters = sp_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
    elif new_slot and overflow and len(header_block.finished_sub_slots) > 1:
        # Start from start of prev slot. Rare case of empty prev slot. Includes genesis block after 2 empty slots
        rc_vdf_challenge = header_block.finished_sub_slots[-2].reward_chain.get_hash()
        sp_vdf_iters = sp_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
    elif prev_sb is None:
        # Genesis block case, first challenge
        rc_vdf_challenge = constants.FIRST_CC_CHALLENGE
        sp_vdf_iters = sp_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
    else:
        # Start from prev block. This is when there is no new slot or if there is a new slot and we overflow
        # but the prev block was is in the same slot (prev slot). This is the normal overflow case.
        rc_vdf_challenge = prev_sb.reward_infusion_output
        sp_vdf_iters = (total_iters - required_iters) + sp_iters - prev_sb.total_iters
        cc_vdf_input = prev_sb.challenge_vdf_output

    # 10. Check reward chain sp proof
    if sp_iters != 0:
        target_vdf_info = VDFInfo(
            rc_vdf_challenge,
            ClassgroupElement.get_default_element(),
            sp_vdf_iters,
            header_block.reward_chain_sub_block.reward_chain_sp_vdf.output,
        )
        if not header_block.reward_chain_sp_proof.is_valid(
            constants,
            header_block.reward_chain_sub_block.reward_chain_sp_vdf,
            target_vdf_info,
        ):
            return None, Err.INVALID_RC_ICP_VDF
        rc_sp_hash = header_block.reward_chain_sub_block.reward_chain_sp_vdf.output.get_hash()
    else:
        # Edge case of first sp (start of slot), where sp_iters == 0
        assert overflow is not None
        if header_block.reward_chain_sub_block.reward_chain_sp_vdf is not None:
            return None, Err.INVALID_RC_ICP_VDF
        rc_sp_hash = header_block.reward_chain_sub_block.proof_of_space.challenge_hash

    # 11. Check reward chain sp signature
    if not AugSchemeMPL.verify(
        header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
        rc_sp_hash,
        header_block.reward_chain_sub_block.reward_chain_sp_signature,
    ):
        return None, Err.INVALID_RC_SIGNATURE

    if prev_sb is None:
        cc_vdf_challenge = constants.FIRST_CC_CHALLENGE
    else:
        if new_slot:
            cc_vdf_challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
        else:
            curr: SubBlockRecord = prev_sb
            while not curr.first_in_slot:
                curr = sub_blocks[curr.prev_hash]
            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

    # 12. Check cc sp
    if sp_iters != 0:
        target_vdf_info = VDFInfo(
            cc_vdf_challenge,
            cc_vdf_input,
            sp_vdf_iters,
            header_block.reward_chain_sub_block.challenge_chain_sp_vdf.output,
        )
        if not header_block.challenge_chain_sp_proof.is_valid(
            constants,
            header_block.reward_chain_sub_block.challenge_chain_sp_vdf,
            target_vdf_info,
        ):
            return None, Err.INVALID_CC_ICP_VDF
    else:
        assert overflow is not None
        if header_block.reward_chain_sub_block.challenge_chain_sp_vdf is not None:
            return None, Err.INVALID_CC_ICP_VDF

    # 13. Check cc sp sig
    if not AugSchemeMPL.verify(
        header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
        cc_sp_hash,
        header_block.reward_chain_sub_block.challenge_chain_sp_signature,
    ):
        return None, Err.INVALID_CC_SIGNATURE

    # 15. Check is_block
    if prev_sb is None:
        if header_block.foliage_sub_block.foliage_block_hash is None:
            return None, Err.INVALID_IS_BLOCK
    else:
        # Finds the previous block
        curr: SubBlockRecord = prev_sb
        while not curr.is_block:
            curr = sub_blocks[curr.prev_hash]

        # The first sub-block to have an sp > the last block's infusion iters, is a block
        if overflow:
            our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters - slot_iters)
        else:
            our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters)
        if (our_sp_total_iters > curr.total_iters) != header_block.foliage_sub_block.foliage_block_hash is not None:
            return None, Err.INVALID_IS_BLOCK

    # 16. Check foliage sub block signature by plot key
    if not AugSchemeMPL.verify(
        header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
        header_block.foliage_sub_block.foliage_sub_block_data.get_hash(),
        header_block.foliage_sub_block.foliage_sub_block_signature,
    ):
        return None, Err.INVALID_PLOT_SIGNATURE

    # 16. Check foliage block signature by plot key
    if header_block.foliage_sub_block.foliage_block_hash is not None:
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            header_block.foliage_sub_block.foliage_block_hash,
            header_block.foliage_sub_block.foliage_block_signature,
        ):
            return None, Err.INVALID_PLOT_SIGNATURE

    # 17. Check unfinished reward chain sub block hash
    if (
        header_block.reward_chain_sub_block.get_hash()
        != header_block.foliage_sub_block.foliage_sub_block_data.unfinished_reward_block_hash
    ):
        return None, Err.INVALID_URSB_HASH

    # 18. Check pool target max height
    if (
        header_block.foliage_sub_block.foliage_sub_block_data.pool_target.max_height != 0
        and header_block.foliage_sub_block.foliage_sub_block_data.pool_target.max_height < header_block.height
    ):
        return None, Err.OLD_POOL_TARGET

    # 19. Check pool target signature
    if not AugSchemeMPL.verify(
        header_block.reward_chain_sub_block.proof_of_space.pool_public_key,
        bytes(header_block.foliage_sub_block.foliage_sub_block_data.pool_target),
        header_block.foliage_sub_block.foliage_sub_block_data.pool_signature,
    ):
        return None, Err.INVALID_POOL_SIGNATURE

    # 20. Check extension data if applicable. None for mainnet.
    # 21. Check if foliage block is present
    if (header_block.foliage_sub_block.foliage_block_hash is not None) != (header_block.foliage_block is not None):
        return None, Err.INVALID_FOLIAGE_BLOCK_PRESENCE

    if (header_block.foliage_sub_block.foliage_sub_block_signature is not None) != (
        header_block.foliage_block is not None
    ):
        return None, Err.INVALID_FOLIAGE_BLOCK_PRESENCE

    if header_block.foliage_block is not None:
        # 22. Check foliage block hash
        if header_block.foliage_block.get_hash() != header_block.foliage_sub_block.foliage_block_hash:
            return None, Err.INVALID_FOLIAGE_BLOCK_HASH

        # 23. Check prev block hash
        if prev_sb is None:
            if header_block.foliage_block.prev_block_hash != bytes([0] * 32):
                return None, Err.INVALID_PREV_BLOCK_HASH
        else:
            curr_sb: SubBlockRecord = prev_sb
            while not curr_sb.is_block:
                curr_sb = sub_blocks[curr_sb.prev_hash]
            if not header_block.foliage_block.prev_block_hash == curr_sb.header_hash:
                return None, Err.INVALID_PREV_BLOCK_HASH

        # 24. The filter hash in the Foliage Block must be the hash of the filter
        if check_filter:
            if header_block.foliage_block.filter_hash != std_hash(header_block.transactions_filter):
                return None, Err.INVALID_TRANSACTIONS_FILTER_HASH

        # 25. The timestamp in Foliage Block must comply with the timestamp rules
        if prev_sb is not None:
            last_timestamps: List[uint64] = []
            curr_sb: SubBlockRecord = sub_blocks[header_block.foliage_block.prev_block_hash]
            while len(last_timestamps) < constants.NUMBER_OF_TIMESTAMPS:
                last_timestamps.append(curr_sb.timestamp)
                fetched: Optional[SubBlockRecord] = sub_blocks.get(curr_sb.prev_block_hash, None)
                if not fetched:
                    break
                curr_sb = fetched
            if len(last_timestamps) != constants.NUMBER_OF_TIMESTAMPS:
                # For blocks 1 to 10, average timestamps of all previous blocks
                assert curr_sb.height == 0
            prev_time: uint64 = uint64(int(sum(last_timestamps) // len(last_timestamps)))
            if header_block.foliage_block.timestamp < prev_time:
                return None, Err.TIMESTAMP_TOO_FAR_IN_PAST
            if header_block.foliage_block.timestamp > int(time.time() + constants.MAX_FUTURE_TIME):
                return None, Err.TIMESTAMP_TOO_FAR_IN_FUTURE

    return required_iters, None  # Valid unfinished header block


async def validate_finished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: HeaderBlock,
    check_filter: bool,
) -> Tuple[Optional[uint64], Optional[Err]]:
    """
    Fully validates the header of a sub-block. A header block is the same as a full block, but
    without transactions and transaction info. Returns (required_iters, error).
    """
    unfinished_header_block = UnfinishedHeaderBlock(
        header_block.finished_sub_slots,
        header_block.reward_chain_sub_block.get_unfinished(),
        header_block.challenge_chain_sp_proof,
        header_block.reward_chain_sp_proof,
        header_block.foliage_sub_block,
        header_block.foliage_block,
        header_block.transactions_filter,
    )

    required_iters, validate_unfinished_result = await validate_unfinished_header_block(
        constants, sub_blocks, height_to_hash, unfinished_header_block, check_filter
    )

    if validate_unfinished_result is not None:
        return None, validate_unfinished_result
    if header_block.height == 0:
        prev_sb: Optional[SubBlockRecord] = None
    else:
        prev_sb: Optional[SubBlockRecord] = sub_blocks[header_block.prev_header_hash]
    new_slot: bool = len(header_block.finished_sub_slots) > 0
    if prev_sb is None:
        ips = uint64(constants.IPS_STARTING)
    else:
        ips: uint64 = get_next_ips(
            constants,
            sub_blocks,
            height_to_hash,
            header_block.prev_header_hash,
            prev_sb.height,
            prev_sb.deficit,
            prev_sb.ips,
            True,
            prev_sb.total_iters,
        )
    ip_iters: uint64 = calculate_ip_iters(constants, ips, required_iters)

    # RC vdf challenge is taken from more recent of (slot start, prev_block)
    icc_vdf_output = ClassgroupElement.get_default_element()
    if prev_sb is None:
        cc_vdf_output = ClassgroupElement.get_default_element()
        ip_vdf_iters = ip_iters
        if new_slot:
            rc_vdf_challenge = header_block.finished_sub_slots[-1].reward_chain.get_hash()
        else:
            rc_vdf_challenge = constants.FIRST_RC_CHALLENGE
    else:
        if new_slot:
            # slot start is more recent
            rc_vdf_challenge = header_block.finished_sub_slots[-1].reward_chain.get_hash()
            ip_vdf_iters = ip_iters
            cc_vdf_output = ClassgroupElement.get_default_element()

        else:
            # Prev sb is more recent
            rc_vdf_challenge: bytes32 = prev_sb.reward_infusion_output
            ip_vdf_iters: uint64 = uint64(
                header_block.reward_chain_sub_block.total_iters - prev_sb.total_iters
            )
            cc_vdf_output = prev_sb.challenge_vdf_output
            icc_vdf_output = prev_sb.infused_challenge_vdf_output

    # 26. Check challenge chain infusion point VDF
    if new_slot:
        cc_vdf_challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
    else:
        # Not first sub-block in slot
        if prev_sb is None:
            # Genesis block
            cc_vdf_challenge = constants.FIRST_CC_CHALLENGE
        else:
            # Not genesis block, go back to first sub-block in slot
            curr = prev_sb
            while curr.finished_challenge_slot_hashes is None:
                curr = sub_blocks[curr.prev_hash]
            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

    cc_target_vdf_info = VDFInfo(
        cc_vdf_challenge,
        cc_vdf_output,
        ip_vdf_iters,
        header_block.reward_chain_sub_block.challenge_chain_ip_vdf.output,
    )
    if not header_block.challenge_chain_ip_proof.is_valid(
        constants,
        header_block.reward_chain_sub_block.challenge_chain_ip_vdf,
        cc_target_vdf_info,
    ):
        return None, Err.INVALID_CC_IP_VDF

    # 27. Check reward chain infusion point VDF
    rc_target_vdf_info = VDFInfo(
        rc_vdf_challenge,
        ClassgroupElement.get_default_element(),
        ip_vdf_iters,
        header_block.reward_chain_sub_block.reward_chain_ip_vdf.output,
    )
    if not header_block.reward_chain_ip_proof.is_valid(
        constants,
        header_block.reward_chain_sub_block.reward_chain_ip_vdf,
        rc_target_vdf_info,
    ):
        return None, Err.INVALID_RC_IP_VDF

    # 28. Check infused challenge chain infusion point VDF
    if prev_sb is not None:
        overflow = is_overflow_sub_block(constants, ips, required_iters)
        deficit = calculate_deficit(
            constants, header_block.height, prev_sb, overflow, header_block.finished_sub_slots is not None
        )

        if header_block.reward_chain_sub_block.infused_challenge_chain_ip_vdf is None:
            # If we don't have an ICC chain, deficit must be 4 or 5
            if deficit < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                return None, Err.INVALID_ICC_VDF
        else:
            # If we have an ICC chain, deficit must be 0, 1, 2 or 3
            if deficit >= constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                return None, Err.INVALID_ICC_VDF
            if new_slot:
                icc_vdf_challenge: bytes32 = header_block.finished_sub_slots[-1].infused_challenge_chain.get_hash()
            else:
                curr = prev_sb
                while curr.finished_infused_challenge_slot_hashes is None:
                    curr = sub_blocks[curr.prev_hash]
                icc_vdf_challenge: bytes32 = curr.finished_infused_challenge_slot_hashes[-1]

            icc_target_vdf_info = VDFInfo(
                icc_vdf_challenge,
                icc_vdf_output,
                ip_vdf_iters,
                header_block.reward_chain_sub_block.infused_challenge_chain_ip_vdf.output,
            )
            if not header_block.infused_challenge_chain_ip_proof.is_valid(
                constants,
                header_block.reward_chain_sub_block.infused_challenge_chain_ip_vdf,
                icc_target_vdf_info,
            ):
                return None, Err.INVALID_ICC_VDF
    else:
        if header_block.infused_challenge_chain_ip_proof is not None:
            return None, Err.INVALID_ICC_VDF

    # 29. Check reward block hash
    if header_block.foliage_sub_block.reward_block_hash != header_block.reward_chain_sub_block.get_hash():
        return None, Err.INVALID_REWARD_BLOCK_HASH

    # 30. Check reward block is_block
    if (header_block.foliage_sub_block.foliage_block_hash is not None) != header_block.reward_chain_sub_block.is_block:
        return None, Err.INVALID_FOLIAGE_BLOCK_PRESENCE

    return required_iters, None
