import dataclasses
import logging
import time
from typing import Dict, Optional, List, Tuple

from blspy import AugSchemeMPL

from src.consensus.constants import ConsensusConstants
from src.consensus.deficit import calculate_deficit
from src.consensus.difficulty_adjustment import (
    can_finish_sub_and_full_epoch,
    get_sub_slot_iters_and_difficulty,
)
from src.consensus.get_block_challenge import get_block_challenge
from src.consensus.make_sub_epoch_summary import make_sub_epoch_summary
from src.consensus.pot_iterations import (
    is_overflow_sub_block,
    calculate_ip_iters,
    calculate_sp_iters,
    calculate_iterations_quality,
)
from src.consensus.vdf_info_computation import get_signage_point_vdf_info
from src.consensus.sub_block_record import SubBlockRecord
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
from src.types.unfinished_header_block import UnfinishedHeaderBlock
from src.types.vdf import VDFInfo, VDFProof
from src.util.errors import Err, ValidationError
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint128, uint8

log = logging.getLogger(__name__)


# noinspection PyCallByClass
async def validate_unfinished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: UnfinishedHeaderBlock,
    check_filter: bool,
    skip_overflow_last_ss_validation: bool = False,
) -> Tuple[Optional[uint64], Optional[ValidationError]]:
    """
    Validates an unfinished header block. This is a block without the infusion VDFs (unfinished)
    and without transactions and transaction info (header). Returns (required_iters, error).

    This method is meant to validate only the unfinished part of the sub-block. However, the finished_sub_slots
    refers to all sub-slots that were finishes from the previous sub-block's infusion point, up to this sub-blocks
    infusion point. Therefore, in the case where this is an overflow sub-block, and the last sub-slot is not yet
    released, header_block.finished_sub_slots will be missing one sub-slot. In this case,
    skip_overflow_last_ss_validation must be set to True. This will skip validation of end of slots, sub-epochs,
    and lead to other small tweaks in validation.
    """
    # 1. Check that the previous block exists in the blockchain, or that it is correct

    prev_sb = sub_blocks.get(header_block.prev_header_hash, None)
    genesis_block = prev_sb is None

    if genesis_block and header_block.prev_header_hash != constants.GENESIS_PREV_HASH:
        return None, ValidationError(Err.INVALID_PREV_BLOCK_HASH)

    overflow = is_overflow_sub_block(constants, header_block.reward_chain_sub_block.signage_point_index)
    if skip_overflow_last_ss_validation and overflow:
        finished_sub_slots_since_prev = len(header_block.finished_sub_slots) + 1
    else:
        finished_sub_slots_since_prev = len(header_block.finished_sub_slots)

    new_sub_slot: bool = finished_sub_slots_since_prev > 0

    can_finish_se: bool = False
    can_finish_epoch: bool = False
    if genesis_block:
        height: uint32 = uint32(0)
        sub_slot_iters = constants.SUB_SLOT_ITERS_STARTING
        difficulty = constants.DIFFICULTY_STARTING
    else:
        height: uint32 = uint32(prev_sb.sub_block_height + 1)
        if prev_sb.sub_epoch_summary_included is not None:
            can_finish_se, can_finish_epoch = False, False
        else:
            can_finish_se, can_finish_epoch = can_finish_sub_and_full_epoch(
                constants, prev_sb.sub_block_height, prev_sb.deficit, sub_blocks, prev_sb.prev_hash, False
            )
        can_finish_se = can_finish_se and new_sub_slot
        can_finish_epoch = can_finish_epoch and new_sub_slot

        # Gets the difficulty and SSI for this sub-block
        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
            constants, header_block, height_to_hash, prev_sb, sub_blocks
        )

    # 2. Check finished slots that have been crossed since prev_sb
    ses_hash: Optional[bytes32] = None
    if new_sub_slot and not skip_overflow_last_ss_validation:
        # Finished a slot(s) since previous block. The first sub-slot must have at least one sub-block, and all
        # subsequent sub-slots must be empty
        for finished_sub_slot_n, sub_slot in enumerate(header_block.finished_sub_slots):
            # Start of slot challenge is fetched from SP
            challenge_hash: bytes32 = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge

            if finished_sub_slot_n == 0:
                if genesis_block:
                    # 2a. check sub-slot challenge hash for genesis block
                    if challenge_hash != constants.FIRST_CC_CHALLENGE:
                        return None, ValidationError(Err.INVALID_PREV_CHALLENGE_SLOT_HASH)
                else:
                    curr: SubBlockRecord = prev_sb
                    while not curr.first_in_sub_slot:
                        curr = sub_blocks[curr.prev_hash]

                    # 2b. check sub-slot challenge hash for non-genesis block
                    if not curr.finished_challenge_slot_hashes[-1] == challenge_hash:
                        return None, ValidationError(Err.INVALID_PREV_CHALLENGE_SLOT_HASH)
            else:
                # 2c. check sub-slot challenge hash for empty slot
                if (
                    not header_block.finished_sub_slots[finished_sub_slot_n - 1].challenge_chain.get_hash()
                    == challenge_hash
                ):
                    return None, ValidationError(Err.INVALID_PREV_CHALLENGE_SLOT_HASH)

            if genesis_block:
                # 2d. Validate that genesis block has no ICC
                if sub_slot.infused_challenge_chain is not None:
                    return None, ValidationError(Err.SHOULD_NOT_HAVE_ICC)
            else:
                icc_iters_committed: Optional[uint64] = None
                icc_iters_proof: Optional[uint64] = None
                icc_challenge_hash: Optional[bytes32] = None
                icc_vdf_input = None
                if prev_sb.deficit < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    # There should be no ICC chain if the last sub block's deficit is 16
                    # Prev sb's deficit is 0, 1, 2, 3, or 4
                    if finished_sub_slot_n == 0:
                        # This is the first sub slot after the last sb, which must have deficit 1-4, and thus an ICC
                        curr: SubBlockRecord = prev_sb
                        while not curr.is_challenge_sub_block(constants) and not curr.first_in_sub_slot:
                            curr = sub_blocks[curr.prev_hash]
                        if curr.is_challenge_sub_block(constants):
                            icc_challenge_hash = curr.challenge_block_info_hash
                            icc_iters_committed: uint64 = prev_sb.sub_slot_iters - curr.ip_iters(constants)
                        else:
                            icc_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
                            icc_iters_committed = prev_sb.sub_slot_iters
                        icc_iters_proof: uint64 = prev_sb.sub_slot_iters - prev_sb.ip_iters(constants)
                        if prev_sb.is_challenge_sub_block(constants):
                            icc_vdf_input = ClassgroupElement.get_default_element()
                        else:
                            icc_vdf_input = prev_sb.infused_challenge_vdf_output
                    else:
                        # This is not the first sub slot after the last sub block, so we might not have an ICC
                        if (
                            header_block.finished_sub_slots[finished_sub_slot_n - 1].reward_chain.deficit
                            < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
                        ):
                            # Only sets the icc iff the previous sub slots deficit is 4 or less
                            icc_challenge_hash = header_block.finished_sub_slots[
                                finished_sub_slot_n - 1
                            ].infused_challenge_chain.get_hash()
                            icc_iters_committed = prev_sb.sub_slot_iters
                            icc_iters_proof = icc_iters_committed
                            icc_vdf_input = ClassgroupElement.get_default_element()

                # 2e. Validate that there is not icc iff icc_challenge hash is None
                assert (sub_slot.infused_challenge_chain is None) == (icc_challenge_hash is None)
                if sub_slot.infused_challenge_chain is not None:
                    assert icc_vdf_input is not None
                    # 2f. Check infused challenge chain sub-slot VDF
                    # Only validate from prev_sb to optimize
                    target_vdf_info = VDFInfo(
                        icc_challenge_hash,
                        icc_iters_proof,
                        sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output,
                    )
                    if sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf != dataclasses.replace(
                        target_vdf_info,
                        number_of_iterations=icc_iters_committed,
                    ):
                        return None, ValidationError(Err.INVALID_ICC_EOS_VDF)
                    if not sub_slot.proofs.infused_challenge_chain_slot_proof.is_valid(
                        constants, icc_vdf_input, target_vdf_info, None
                    ):
                        return None, ValidationError(Err.INVALID_ICC_EOS_VDF)

                    if sub_slot.reward_chain.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        # 2g. Check infused challenge sub-slot hash in challenge chain, deficit 16
                        if (
                            sub_slot.infused_challenge_chain.get_hash()
                            != sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash
                        ):
                            return None, ValidationError(Err.INVALID_ICC_HASH_CC)
                    else:
                        # 2h. Check infused challenge sub-slot hash not included for other deficits
                        if sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash is not None:
                            return None, ValidationError(Err.INVALID_ICC_HASH_CC)

                    # 2i. Check infused challenge sub-slot hash in reward sub-slot
                    if (
                        sub_slot.infused_challenge_chain.get_hash()
                        != sub_slot.reward_chain.infused_challenge_chain_sub_slot_hash
                    ):
                        return None, ValidationError(Err.INVALID_ICC_HASH_RC)
                else:
                    # 2j. If no icc, check that the cc doesn't include it
                    if sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash is not None:
                        return None, ValidationError(Err.INVALID_ICC_HASH_CC)

                    # 2k. If no icc, check that the cc doesn't include it
                    if sub_slot.reward_chain.infused_challenge_chain_sub_slot_hash is not None:
                        return None, ValidationError(Err.INVALID_ICC_HASH_RC)

            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                assert ses_hash is None  # Only one of the slots can have it
                ses_hash = sub_slot.challenge_chain.subepoch_summary_hash

            # 2l. check sub-epoch summary hash is None for empty slots
            if finished_sub_slot_n != 0:
                if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                    return None, ValidationError(Err.INVALID_SUB_EPOCH_SUMMARY_HASH)

            if can_finish_epoch and sub_slot.challenge_chain.subepoch_summary_hash is not None:
                # 2m. Check new difficulty and ssi
                if sub_slot.challenge_chain.new_sub_slot_iters != sub_slot_iters:
                    return None, ValidationError(Err.INVALID_NEW_SUB_SLOT_ITERS)
                if sub_slot.challenge_chain.new_difficulty != difficulty:
                    return None, ValidationError(Err.INVALID_NEW_DIFFICULTY)
            else:
                # 2n. Check new difficulty and ssi are None if we don't finish epoch
                if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                    return None, ValidationError(Err.INVALID_NEW_SUB_SLOT_ITERS)
                if sub_slot.challenge_chain.new_difficulty is not None:
                    return None, ValidationError(Err.INVALID_NEW_DIFFICULTY)

            # 2o. Check challenge sub-slot hash in reward sub-slot
            if sub_slot.challenge_chain.get_hash() != sub_slot.reward_chain.challenge_chain_sub_slot_hash:
                return None, ValidationError(
                    Err.INVALID_CHALLENGE_SLOT_HASH_RC, "sub-slot hash in reward sub-slot mismatch"
                )

            eos_vdf_iters: uint64 = sub_slot_iters
            cc_start_element: ClassgroupElement = ClassgroupElement.get_default_element()
            cc_eos_vdf_challenge: bytes32 = challenge_hash
            if genesis_block:
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
                    rc_eos_vdf_challenge: bytes32 = prev_sb.reward_infusion_new_challenge
                    eos_vdf_iters = prev_sb.sub_slot_iters - prev_sb.ip_iters(constants)
                    cc_start_element: ClassgroupElement = prev_sb.challenge_vdf_output
                else:
                    # At least one empty slot, so use previous slot hash. IPS might change because it's a new slot
                    rc_eos_vdf_challenge: bytes32 = header_block.finished_sub_slots[
                        finished_sub_slot_n - 1
                    ].reward_chain.get_hash()

            # 2p. Check end of reward slot VDF
            target_vdf_info = VDFInfo(
                rc_eos_vdf_challenge,
                eos_vdf_iters,
                sub_slot.reward_chain.end_of_slot_vdf.output,
            )
            if not sub_slot.proofs.reward_chain_slot_proof.is_valid(
                constants,
                ClassgroupElement.get_default_element(),
                sub_slot.reward_chain.end_of_slot_vdf,
                target_vdf_info,
            ):
                return None, ValidationError(Err.INVALID_RC_EOS_VDF)

            # 2q. Check challenge chain sub-slot VDF
            partial_cc_vdf_info = VDFInfo(
                cc_eos_vdf_challenge,
                eos_vdf_iters,
                sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output,
            )
            if genesis_block:
                cc_eos_vdf_info_iters = constants.SUB_SLOT_ITERS_STARTING
            else:
                if finished_sub_slot_n == 0:
                    cc_eos_vdf_info_iters = prev_sb.sub_slot_iters
                else:
                    cc_eos_vdf_info_iters = sub_slot_iters
            # Check that the modified data is correct
            if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf != dataclasses.replace(
                partial_cc_vdf_info,
                number_of_iterations=cc_eos_vdf_info_iters,
            ):
                return None, ValidationError(Err.INVALID_CC_EOS_VDF, "wrong challenge chain end of slot vdf")

            # Pass in None for target info since we are only checking the proof from the temporary point,
            # but the challenge_chain_end_of_slot_vdf actually starts from the start of slot (for light clients)
            if not sub_slot.proofs.challenge_chain_slot_proof.is_valid(
                constants, cc_start_element, partial_cc_vdf_info, None
            ):
                return None, ValidationError(Err.INVALID_CC_EOS_VDF)

            if genesis_block:
                # 2r. Check deficit (MIN_SUB.. deficit edge case for genesis block)
                if sub_slot.reward_chain.deficit != constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    return None, ValidationError(
                        Err.INVALID_DEFICIT, f"genesis, expected deficit {constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK}"
                    )
            else:
                if prev_sb.deficit == 0:
                    # 2s. If prev sb had deficit 0, resets deficit to MIN_SUB_BLOCK_PER_CHALLENGE_BLOCK
                    if sub_slot.reward_chain.deficit != constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        log.error(
                            constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK,
                        )
                        return None, ValidationError(
                            Err.INVALID_DEFICIT,
                            f"expected deficit {constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK}, saw "
                            f"{sub_slot.reward_chain.deficit}",
                        )
                else:
                    # 2t. Otherwise, deficit stays the same at the slot ends, cannot reset until 0
                    if sub_slot.reward_chain.deficit != prev_sb.deficit:
                        return None, ValidationError(Err.INVALID_DEFICIT, "deficit is wrong at slot end")

        # 3. Check sub-epoch summary
        # Note that the subepoch summary is the summary of the previous subepoch (not the one that just finished)
        if not skip_overflow_last_ss_validation:
            if ses_hash is not None:
                # 3a. Check that genesis block does not have sub-epoch summary
                if genesis_block:
                    return None, ValidationError(
                        Err.INVALID_SUB_EPOCH_SUMMARY_HASH, "genesis with sub-epoch-summary hash"
                    )

                # 3b. Check that we finished a slot and we finished a sub-epoch
                if not new_sub_slot or not can_finish_se:
                    return None, ValidationError(
                        Err.INVALID_SUB_EPOCH_SUMMARY_HASH,
                        f"new sub-slot: {new_sub_slot} finishes sub-epoch {can_finish_se}",
                    )

                # 3c. Check the actual sub-epoch is correct
                expected_sub_epoch_summary = make_sub_epoch_summary(
                    constants,
                    sub_blocks,
                    uint32(prev_sb.sub_block_height + 1),
                    sub_blocks[prev_sb.prev_hash],
                    difficulty if can_finish_epoch else None,
                    sub_slot_iters if can_finish_epoch else None,
                )
                expected_hash = expected_sub_epoch_summary.get_hash()
                if expected_hash != ses_hash:
                    log.error(f"{expected_sub_epoch_summary}")
                    return None, ValidationError(
                        Err.INVALID_SUB_EPOCH_SUMMARY, f"expected ses hash: {expected_hash} got {ses_hash} "
                    )
            elif new_sub_slot and not genesis_block:
                # 3d. Check that we don't have to include a sub-epoch summary
                if can_finish_se or can_finish_epoch:
                    return None, ValidationError(
                        Err.INVALID_SUB_EPOCH_SUMMARY, "block finishes sub-epoch but ses-hash is None"
                    )

    # 4. Check if the number of sub-blocks is less than the max
    if not new_sub_slot and not genesis_block:
        num_sub_blocks = 2  # This includes the current sub-block and the prev sub-block
        curr = prev_sb
        while not curr.first_in_sub_slot:
            num_sub_blocks += 1
            curr = sub_blocks[curr.prev_hash]
        if num_sub_blocks > constants.MAX_SUB_SLOT_SUB_BLOCKS:
            return None, ValidationError(Err.TOO_MANY_SUB_BLOCKS)

    # If sub_block state is correct, we should always find a challenge here
    # This computes what the challenge should be for this sub-block

    challenge = get_block_challenge(
        constants,
        header_block,
        sub_blocks,
        genesis_block,
        overflow,
        skip_overflow_last_ss_validation,
    )

    # 5a. Check proof of space
    if challenge != header_block.reward_chain_sub_block.pos_ss_cc_challenge_hash:
        log.error(f"Finished slots: {header_block.finished_sub_slots}")
        log.error(
            f"Data: {genesis_block} {overflow} {skip_overflow_last_ss_validation} {header_block.total_iters} "
            f"{header_block.reward_chain_sub_block.signage_point_index}"
        )
        log.error(f"Challenge {challenge} provided {header_block.reward_chain_sub_block.pos_ss_cc_challenge_hash}")
        return None, ValidationError(Err.INVALID_CC_CHALLENGE)

    # 5b. Check proof of space
    if header_block.reward_chain_sub_block.challenge_chain_sp_vdf is None:
        # Edge case of first sp (start of slot), where sp_iters == 0
        cc_sp_hash: bytes32 = challenge
    else:
        cc_sp_hash = header_block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash()

    q_str: Optional[bytes32] = header_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
        constants, challenge, cc_sp_hash
    )
    if q_str is None:
        return None, ValidationError(Err.INVALID_POSPACE)

    # 6. check signage point index
    # no need to check negative values as this is uint 8
    if header_block.reward_chain_sub_block.signage_point_index >= constants.NUM_SPS_SUB_SLOT:
        return None, ValidationError(Err.INVALID_SP_INDEX)

    # Note that required iters might be from the previous slot (if we are in an overflow sub-block)
    required_iters: uint64 = calculate_iterations_quality(
        q_str,
        header_block.reward_chain_sub_block.proof_of_space.size,
        difficulty,
        cc_sp_hash,
    )

    # 7. check signage point index
    # no need to check negative values as this is uint8. (Assumes types are checked)
    if header_block.reward_chain_sub_block.signage_point_index >= constants.NUM_SPS_SUB_SLOT:
        return None, ValidationError(Err.INVALID_SP_INDEX)

    # 8a. check signage point index 0 has no cc sp
    if (header_block.reward_chain_sub_block.signage_point_index == 0) != (
        header_block.reward_chain_sub_block.challenge_chain_sp_vdf is None
    ):
        return None, ValidationError(Err.INVALID_SP_INDEX)

    # 8b. check signage point index 0 has no rc sp
    if (header_block.reward_chain_sub_block.signage_point_index == 0) != (
        header_block.reward_chain_sub_block.reward_chain_sp_vdf is None
    ):
        return None, ValidationError(Err.INVALID_SP_INDEX)

    sp_iters: uint64 = calculate_sp_iters(
        constants, sub_slot_iters, header_block.reward_chain_sub_block.signage_point_index
    )

    ip_iters: uint64 = calculate_ip_iters(
        constants, sub_slot_iters, header_block.reward_chain_sub_block.signage_point_index, required_iters
    )
    if header_block.reward_chain_sub_block.challenge_chain_sp_vdf is None:
        # Blocks with very low required iters are not overflow blocks
        assert not overflow

    # 9. Check no overflows in the first sub-slot of a new epoch
    # (although they are OK in the second sub-slot), this is important
    if overflow and can_finish_epoch:
        if finished_sub_slots_since_prev < 2:
            return None, ValidationError(Err.NO_OVERFLOWS_IN_FIRST_SUB_SLOT_NEW_EPOCH)

    # 10. Check total iters
    if genesis_block:
        total_iters: uint128 = uint128(sub_slot_iters * finished_sub_slots_since_prev)
    else:
        if new_sub_slot:
            total_iters: uint128 = prev_sb.total_iters
            # Add the rest of the slot of prev_sb
            total_iters += prev_sb.sub_slot_iters - prev_sb.ip_iters(constants)
            # Add other empty slots
            total_iters = total_iters + (sub_slot_iters * (finished_sub_slots_since_prev - 1))
        else:
            # Slot iters is guaranteed to be the same for header_block and prev_sb
            # This takes the beginning of the slot, and adds ip_iters
            total_iters = uint128(prev_sb.total_iters - prev_sb.ip_iters(constants))
    total_iters += ip_iters
    if total_iters != header_block.reward_chain_sub_block.total_iters:
        return None, ValidationError(
            Err.INVALID_TOTAL_ITERS, f"expected {total_iters} got {header_block.reward_chain_sub_block.total_iters}"
        )

    sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters - (sub_slot_iters if overflow else 0))
    if overflow and skip_overflow_last_ss_validation:
        dummy_vdf_info = VDFInfo(
            bytes([0] * 32),
            uint64(1),
            ClassgroupElement.get_default_element(),
        )
        dummy_sub_slot = EndOfSubSlotBundle(
            ChallengeChainSubSlot(dummy_vdf_info, None, None, None, None),
            None,
            RewardChainSubSlot(dummy_vdf_info, bytes([0] * 32), None, uint8(0)),
            SubSlotProofs(VDFProof(uint8(0), b""), None, VDFProof(uint8(0), b"")),
        )
        sub_slots_to_pass_in = header_block.finished_sub_slots + [dummy_sub_slot]
    else:
        sub_slots_to_pass_in = header_block.finished_sub_slots
    (
        cc_vdf_challenge,
        rc_vdf_challenge,
        cc_vdf_input,
        rc_vdf_input,
        cc_vdf_iters,
        rc_vdf_iters,
    ) = get_signage_point_vdf_info(
        constants, sub_slots_to_pass_in, overflow, prev_sb, sub_blocks, sp_total_iters, sp_iters
    )

    # 11. Check reward chain sp proof
    if sp_iters != 0:
        target_vdf_info = VDFInfo(
            rc_vdf_challenge,
            rc_vdf_iters,
            header_block.reward_chain_sub_block.reward_chain_sp_vdf.output,
        )
        if not header_block.reward_chain_sp_proof.is_valid(
            constants,
            rc_vdf_input,
            header_block.reward_chain_sub_block.reward_chain_sp_vdf,
            target_vdf_info,
        ):
            log.error("block %s failed validation, invalid rc vdf ", header_block.header_hash)
            return None, ValidationError(Err.INVALID_RC_SP_VDF)
        rc_sp_hash = header_block.reward_chain_sub_block.reward_chain_sp_vdf.output.get_hash()
    else:
        # Edge case of first sp (start of slot), where sp_iters == 0
        assert overflow is not None
        if header_block.reward_chain_sub_block.reward_chain_sp_vdf is not None:
            log.error("block %s failed validation rc vdf is not None ", header_block.header_hash)
            return None, ValidationError(Err.INVALID_RC_SP_VDF)
        if new_sub_slot:
            rc_sp_hash = header_block.finished_sub_slots[-1].reward_chain.get_hash()
        else:
            if genesis_block:
                rc_sp_hash = constants.FIRST_RC_CHALLENGE
            else:
                curr = prev_sb
                while not curr.first_in_sub_slot:
                    curr = sub_blocks[curr.prev_hash]
                rc_sp_hash = curr.finished_reward_slot_hashes[-1]

    # 12. Check reward chain sp signature
    if not AugSchemeMPL.verify(
        header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
        rc_sp_hash,
        header_block.reward_chain_sub_block.reward_chain_sp_signature,
    ):
        return None, ValidationError(Err.INVALID_RC_SIGNATURE)

    # 13. Check cc sp vdf
    if sp_iters != 0:
        target_vdf_info = VDFInfo(
            cc_vdf_challenge,
            cc_vdf_iters,
            header_block.reward_chain_sub_block.challenge_chain_sp_vdf.output,
        )

        if header_block.reward_chain_sub_block.challenge_chain_sp_vdf != dataclasses.replace(
            target_vdf_info,
            number_of_iterations=sp_iters,
        ):
            return None, ValidationError(Err.INVALID_CC_SP_VDF)
        if not header_block.challenge_chain_sp_proof.is_valid(constants, cc_vdf_input, target_vdf_info, None):
            log.error("block %s failed validation, invalid cc vdf, ", header_block.header_hash)

            return None, ValidationError(Err.INVALID_CC_SP_VDF)
    else:
        assert overflow is not None
        if header_block.reward_chain_sub_block.challenge_chain_sp_vdf is not None:
            log.error("block %s failed validation, overflow should not include cc vdf, ", header_block.header_hash)
            return None, ValidationError(Err.INVALID_CC_SP_VDF)

    # 14. Check cc sp sig
    if not AugSchemeMPL.verify(
        header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
        cc_sp_hash,
        header_block.reward_chain_sub_block.challenge_chain_sp_signature,
    ):
        return None, ValidationError(Err.INVALID_CC_SIGNATURE, "invalid cc sp sig")

    # 15. Check is_block
    if genesis_block:
        if header_block.foliage_sub_block.foliage_block_hash is None:
            return None, ValidationError(Err.INVALID_IS_BLOCK, "invalid genesis")
    else:
        # Finds the previous block
        curr: SubBlockRecord = prev_sb
        while not curr.is_block:
            curr = sub_blocks[curr.prev_hash]

        # The first sub-block to have an sp > the last block's infusion iters, is a block
        if overflow:
            our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters - sub_slot_iters)
        else:
            our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters)
        if (our_sp_total_iters > curr.total_iters) != (header_block.foliage_sub_block.foliage_block_hash is not None):
            return None, ValidationError(Err.INVALID_IS_BLOCK)
        if (our_sp_total_iters > curr.total_iters) != (
            header_block.foliage_sub_block.foliage_block_signature is not None
        ):
            return None, ValidationError(Err.INVALID_IS_BLOCK)

    # 16. Check foliage sub block signature by plot key
    if not AugSchemeMPL.verify(
        header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
        header_block.foliage_sub_block.foliage_sub_block_data.get_hash(),
        header_block.foliage_sub_block.foliage_sub_block_signature,
    ):
        return None, ValidationError(Err.INVALID_PLOT_SIGNATURE)

    # 17. Check foliage block signature by plot key
    if header_block.foliage_sub_block.foliage_block_hash is not None:
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            header_block.foliage_sub_block.foliage_block_hash,
            header_block.foliage_sub_block.foliage_block_signature,
        ):
            return None, ValidationError(Err.INVALID_PLOT_SIGNATURE)

    # 18. Check unfinished reward chain sub block hash
    if (
        header_block.reward_chain_sub_block.get_hash()
        != header_block.foliage_sub_block.foliage_sub_block_data.unfinished_reward_block_hash
    ):
        return None, ValidationError(Err.INVALID_URSB_HASH)

    # 19. Check pool target max height
    if (
        header_block.foliage_sub_block.foliage_sub_block_data.pool_target.max_height != 0
        and header_block.foliage_sub_block.foliage_sub_block_data.pool_target.max_height < height
    ):
        return None, ValidationError(Err.OLD_POOL_TARGET)

    # 20a. Check pre-farm puzzle hash for genesis sub-block.
    if genesis_block:
        if (
            header_block.foliage_sub_block.foliage_sub_block_data.pool_target.puzzle_hash
            != constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH
        ):
            log.error(f"Pool target {header_block.foliage_sub_block.foliage_sub_block_data.pool_target}")
            return None, ValidationError(Err.INVALID_PREFARM)
    else:
        # 20b. Check pool target signature. Should not check this for genesis sub-block.
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.pool_public_key,
            bytes(header_block.foliage_sub_block.foliage_sub_block_data.pool_target),
            header_block.foliage_sub_block.foliage_sub_block_data.pool_signature,
        ):
            return None, ValidationError(Err.INVALID_POOL_SIGNATURE)

    # 21. Check extension data if applicable. None for mainnet.
    # 22. Check if foliage block is present
    if (header_block.foliage_sub_block.foliage_block_hash is not None) != (header_block.foliage_block is not None):
        return None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_PRESENCE)

    if (header_block.foliage_sub_block.foliage_block_signature is not None) != (header_block.foliage_block is not None):
        return None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_PRESENCE)

    if header_block.foliage_block is not None:
        # 23. Check foliage block hash
        if header_block.foliage_block.get_hash() != header_block.foliage_sub_block.foliage_block_hash:
            return None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_HASH)

        if genesis_block:
            # 24a. Check prev block hash for genesis
            if header_block.foliage_block.prev_block_hash != bytes([0] * 32):
                return None, ValidationError(Err.INVALID_PREV_BLOCK_HASH)
        else:
            # 24b. Check prev block hash for non-genesis
            curr_sb: SubBlockRecord = prev_sb
            while not curr_sb.is_block:
                curr_sb = sub_blocks[curr_sb.prev_hash]
            if not header_block.foliage_block.prev_block_hash == curr_sb.header_hash:
                return None, ValidationError(Err.INVALID_PREV_BLOCK_HASH)

        # 25. The filter hash in the Foliage Block must be the hash of the filter
        if check_filter:
            if header_block.foliage_block.filter_hash != std_hash(header_block.transactions_filter):
                return None, ValidationError(Err.INVALID_TRANSACTIONS_FILTER_HASH)

        # 26. The timestamp in Foliage Block must comply with the timestamp rules
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
                assert curr_sb.sub_block_height == 0
            prev_time: uint64 = uint64(int(sum(last_timestamps) // len(last_timestamps)))
            if header_block.foliage_block.timestamp <= prev_time:
                return None, ValidationError(Err.TIMESTAMP_TOO_FAR_IN_PAST)
            if header_block.foliage_block.timestamp > int(time.time() + constants.MAX_FUTURE_TIME):
                return None, ValidationError(Err.TIMESTAMP_TOO_FAR_IN_FUTURE)

    return required_iters, None  # Valid unfinished header block


async def validate_finished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: HeaderBlock,
    check_filter: bool,
) -> Tuple[Optional[uint64], Optional[ValidationError]]:
    """
    Fully validates the header of a sub-block. A header block is the same  as a full block, but
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
        constants, sub_blocks, height_to_hash, unfinished_header_block, check_filter, False
    )

    genesis_block = False
    if validate_unfinished_result is not None:
        return None, validate_unfinished_result
    if header_block.sub_block_height == 0:
        prev_sb: Optional[SubBlockRecord] = None
        genesis_block = True
    else:
        prev_sb: Optional[SubBlockRecord] = sub_blocks[header_block.prev_header_hash]
    new_sub_slot: bool = len(header_block.finished_sub_slots) > 0
    sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
        constants, unfinished_header_block, height_to_hash, prev_sb, sub_blocks
    )
    ip_iters: uint64 = calculate_ip_iters(
        constants, sub_slot_iters, header_block.reward_chain_sub_block.signage_point_index, required_iters
    )
    if not genesis_block:
        # 27. Check sub-block height
        if header_block.sub_block_height != prev_sb.sub_block_height + 1:
            return None, ValidationError(Err.INVALID_HEIGHT)

        # 28. Check weight
        if header_block.weight != prev_sb.weight + difficulty:
            return None, ValidationError(Err.INVALID_WEIGHT)
    else:
        if header_block.sub_block_height != uint32(0):
            return None, ValidationError(Err.INVALID_HEIGHT)
        if header_block.weight != constants.DIFFICULTY_STARTING:
            return None, ValidationError(Err.INVALID_WEIGHT)

    # RC vdf challenge is taken from more recent of (slot start, prev_block)
    if genesis_block:
        cc_vdf_output = ClassgroupElement.get_default_element()
        ip_vdf_iters = ip_iters
        if new_sub_slot:
            rc_vdf_challenge = header_block.finished_sub_slots[-1].reward_chain.get_hash()
        else:
            rc_vdf_challenge = constants.FIRST_RC_CHALLENGE
    else:
        if new_sub_slot:
            # slot start is more recent
            rc_vdf_challenge = header_block.finished_sub_slots[-1].reward_chain.get_hash()
            ip_vdf_iters = ip_iters
            cc_vdf_output = ClassgroupElement.get_default_element()

        else:
            # Prev sb is more recent
            rc_vdf_challenge: bytes32 = prev_sb.reward_infusion_new_challenge
            ip_vdf_iters: uint64 = uint64(header_block.reward_chain_sub_block.total_iters - prev_sb.total_iters)
            cc_vdf_output = prev_sb.challenge_vdf_output

    # 29. Check challenge chain infusion point VDF
    if new_sub_slot:
        cc_vdf_challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
    else:
        # Not first sub-block in slot
        if genesis_block:
            # genesis block
            cc_vdf_challenge = constants.FIRST_CC_CHALLENGE
        else:
            # Not genesis block, go back to first sub-block in slot
            curr = prev_sb
            while curr.finished_challenge_slot_hashes is None:
                curr = sub_blocks[curr.prev_hash]
            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

    cc_target_vdf_info = VDFInfo(
        cc_vdf_challenge,
        ip_vdf_iters,
        header_block.reward_chain_sub_block.challenge_chain_ip_vdf.output,
    )
    if header_block.reward_chain_sub_block.challenge_chain_ip_vdf != dataclasses.replace(
        cc_target_vdf_info,
        number_of_iterations=ip_iters,
    ):
        expected = dataclasses.replace(
            cc_target_vdf_info,
            number_of_iterations=ip_iters,
        )
        log.error(f"{header_block.reward_chain_sub_block.challenge_chain_ip_vdf }. expected {expected}")
        log.error(f"Block: {header_block}")
        return None, ValidationError(Err.INVALID_CC_IP_VDF)
    if not header_block.challenge_chain_ip_proof.is_valid(
        constants,
        cc_vdf_output,
        cc_target_vdf_info,
        None,
    ):
        log.error(f"Did not validate, output {cc_vdf_output}")
        log.error(f"Block: {header_block}")
        return None, ValidationError(Err.INVALID_CC_IP_VDF)

    # 30. Check reward chain infusion point VDF
    rc_target_vdf_info = VDFInfo(
        rc_vdf_challenge,
        ip_vdf_iters,
        header_block.reward_chain_sub_block.reward_chain_ip_vdf.output,
    )
    if not header_block.reward_chain_ip_proof.is_valid(
        constants,
        ClassgroupElement.get_default_element(),
        header_block.reward_chain_sub_block.reward_chain_ip_vdf,
        rc_target_vdf_info,
    ):
        return None, ValidationError(Err.INVALID_RC_IP_VDF)

    # 31. Check infused challenge chain infusion point VDF
    if not genesis_block:
        overflow = is_overflow_sub_block(constants, header_block.reward_chain_sub_block.signage_point_index)
        deficit = calculate_deficit(
            constants, header_block.sub_block_height, prev_sb, overflow, len(header_block.finished_sub_slots)
        )

        if header_block.reward_chain_sub_block.infused_challenge_chain_ip_vdf is None:
            # If we don't have an ICC chain, deficit must be 4 or 5
            if deficit < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                log.error(
                    "no icc vdf and deficit is lower than %d",
                    header_block.header_hash,
                    constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1,
                )
                return None, ValidationError(Err.INVALID_ICC_VDF)
        else:
            # If we have an ICC chain, deficit must be 0, 1, 2 or 3
            if deficit >= constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                return None, ValidationError(
                    Err.INVALID_ICC_VDF,
                    f"icc vdf and deficit is bigger or equal to {constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1}",
                )
            if new_sub_slot:
                icc_vdf_challenge: bytes32 = header_block.finished_sub_slots[-1].infused_challenge_chain.get_hash()
                icc_vdf_input = ClassgroupElement.get_default_element()
            else:
                if prev_sb.is_challenge_sub_block(constants):
                    icc_vdf_input = ClassgroupElement.get_default_element()
                else:
                    icc_vdf_input = prev_sb.infused_challenge_vdf_output
                curr = prev_sb
                while curr.finished_infused_challenge_slot_hashes is None and not curr.is_challenge_sub_block(
                    constants
                ):
                    curr = sub_blocks[curr.prev_hash]

                if curr.is_challenge_sub_block(constants):
                    icc_vdf_challenge: bytes32 = curr.challenge_block_info_hash
                else:
                    assert curr.finished_infused_challenge_slot_hashes is not None
                    icc_vdf_challenge: bytes32 = curr.finished_infused_challenge_slot_hashes[-1]

            icc_target_vdf_info = VDFInfo(
                icc_vdf_challenge,
                ip_vdf_iters,
                header_block.reward_chain_sub_block.infused_challenge_chain_ip_vdf.output,
            )
            if not header_block.infused_challenge_chain_ip_proof.is_valid(
                constants,
                icc_vdf_input,
                header_block.reward_chain_sub_block.infused_challenge_chain_ip_vdf,
                icc_target_vdf_info,
            ):
                return None, ValidationError(Err.INVALID_ICC_VDF, "invalid icc proof")
    else:
        if header_block.infused_challenge_chain_ip_proof is not None:
            return None, ValidationError(Err.INVALID_ICC_VDF)

    # 32. Check reward block hash
    if header_block.foliage_sub_block.reward_block_hash != header_block.reward_chain_sub_block.get_hash():
        return None, ValidationError(Err.INVALID_REWARD_BLOCK_HASH)

    # 33. Check reward block is_block
    if (header_block.foliage_sub_block.foliage_block_hash is not None) != header_block.reward_chain_sub_block.is_block:
        return None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_PRESENCE)

    return required_iters, None
