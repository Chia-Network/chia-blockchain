import logging
from typing import Dict, Optional, List, Tuple
import time

from blspy import AugSchemeMPL

from src.consensus.constants import ConsensusConstants
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
    calculate_icp_iters,
    calculate_slot_iters,
    calculate_iterations_quality,
)
from src.types.challenge_slot import ChallengeChainInfusionPoint
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
    if header_block.height == 0:
        prev_sb: Optional[SubBlockRecord] = None
    else:
        prev_sb: Optional[SubBlockRecord] = sub_blocks[header_block.prev_header_hash]
        if prev_sb is not None:
            return None, Err.DOES_NOT_EXTEND
    new_slot: bool = len(header_block.finished_slots) > 0

    # 2. Check finished slots
    if new_slot:
        # Finished a slot(s) since previous block
        ses_hash: Optional[bytes32] = None
        for finished_slot_n, (challenge_slot, reward_slot, slot_proofs) in enumerate(header_block.finished_slots):
            if challenge_slot.icp_vdf is not None:
                # Start of slot challenge is fetched from ICP
                prev_slot_hash = challenge_slot.icp_vdf.chalenge_hash
            else:
                # Start of slot challenge is fetched from EOS (no infusions in slot)
                prev_slot_hash = challenge_slot.end_of_slot_vdf.challenge_hash

            # 2a. check prev slot hash
            if finished_slot_n == 0:
                if prev_sb is None:
                    if prev_slot_hash != constants.FIRST_CC_CHALLENGE:
                        return None, Err.INVALID_PREV_CHALLENGE_SLOT_HASH
                else:
                    if finished_slot_n == 0:
                        curr: SubBlockRecord = prev_sb
                        while curr.finished_challenge_slot_hashes is None:
                            curr = sub_blocks[curr.prev_hash]
                        assert curr.finished_challenge_slot_hashes is not None
                        if not curr.finished_challenge_slot_hashes[-1] != prev_slot_hash:
                            return None, Err.INVALID_PREV_CHALLENGE_SLOT_HASH
            else:
                if not header_block.finished_slots[finished_slot_n - 1][0].get_hash() == prev_slot_hash:
                    return None, Err.INVALID_PREV_CHALLENGE_SLOT_HASH

            # 2b. check sub-epoch summary hash is None for empty slots
            if challenge_slot.subepoch_summary_hash is not None:
                assert ses_hash is None
                ses_hash = challenge_slot.subepoch_summary_hash
            if finished_slot_n != 0:
                if challenge_slot.subepoch_summary_hash is not None:
                    return None, Err.INVALID_SUB_EPOCH_SUMMARY_HASH

            if challenge_slot.proof_of_space is not None:
                # There is a challenge block in this finished slot
                # 2c. Check that there was a challenge block made in the target slot, and find it
                if finished_slot_n != 0:
                    return None, Err.SHOULD_NOT_MAKE_CHALLENGE_BLOCK
                curr: SubBlockRecord = prev_sb  # prev_sb is guaranteed to be in challenge slot
                while not curr.makes_challenge_block:
                    if curr.finished_challenge_slot_hashes is not None:
                        return None, Err.SHOULD_NOT_MAKE_CHALLENGE_BLOCK
                    curr = sub_blocks[curr.prev_hash]

                assert challenge_slot.icp_signature is not None
                assert challenge_slot.icp_vdf is not None
                assert challenge_slot.ip_vdf is not None

                challenge_infusion_point = ChallengeChainInfusionPoint(
                    challenge_slot.proof_of_space,
                    challenge_slot.icp_vdf,
                    challenge_slot.icp_signature,
                    challenge_slot.ip_vdf,
                ).get_hash()

                # 2d. Check challenge chain end of slot VDF
                ip_iters = calculate_ip_iters(constants, curr.ips, curr.required_iters)
                eos_iters: uint64 = calculate_slot_iters(constants, curr.ips) - ip_iters
                target_vdf_info = VDFInfo(
                    challenge_infusion_point,
                    ClassgroupElement.get_default_element(),
                    eos_iters,
                    challenge_slot.end_of_slot_vdf.output,
                )
                if slot_proofs.challenge_chain_slot_proof.is_valid(
                    constants, challenge_slot.end_of_slot_vdf, target_vdf_info
                ):
                    return None, Err.INVALID_CC_EOS_VDF

            else:
                # There are no challenge blocks in this finished_slot tuple (empty slot)
                # 2f. Check that we are not allowed to make a challenge block
                if finished_slot_n == 0:
                    # If finished_slot_n > 0, guaranteed that we cannot make challenge block, so only checks 0
                    if prev_sb is not None:
                        curr: SubBlockRecord = prev_sb
                        while curr.finished_challenge_slot_hashes is None:
                            if curr.makes_challenge_block:
                                return None, Err.SHOULD_MAKE_CHALLENGE_BLOCK
                            curr = sub_blocks[curr.prev_hash]
                        if curr.makes_challenge_block:
                            return None, Err.SHOULD_MAKE_CHALLENGE_BLOCK

                if prev_sb is None:
                    ips_empty_slots: uint64 = uint64(constants.IPS_STARTING)
                else:
                    # There might be an ips adjustment after the previous block
                    ips_empty_slots: uint64 = get_next_ips(
                        constants, height_to_hash, sub_blocks, header_block.prev_header_hash, True
                    )
                target_vdf_info = VDFInfo(
                    challenge_slot.end_of_slot_vdf.challenge_hash,  # already validated above
                    ClassgroupElement.get_default_element(),
                    calculate_slot_iters(constants, ips_empty_slots),
                    challenge_slot.end_of_slot_vdf.output,
                )
                if not slot_proofs.challenge_chain_slot_proof.is_valid(
                    constants, challenge_slot.end_of_slot_vdf, target_vdf_info
                ):
                    return None, Err.INVALID_CC_EOS_VDF

                # 2g. Check that empty slots have nothing in challenge chain, and no sub-epoch summary
                if (
                    challenge_slot.subepoch_summary_hash is not None
                    or challenge_slot.proof_of_space is not None
                    or challenge_slot.icp_vdf is not None
                    or challenge_slot.icp_signature is not None
                    or challenge_slot.ip_vdf is not None
                ):
                    return None, Err.INVALID_CHALLENGE_CHAIN_DATA

            # 2h. Check challenge slot hash in reward slot
            if reward_slot.challenge_slot_hash != challenge_slot.get_hash():
                return None, Err.INVALID_CHALLENGE_SLOT_HASH_RC

            # 2i. Check end of reward slot VDF
            if prev_sb is None:
                ips: uint64 = uint64(constants.IPS_STARTING)
                rc_eos_vdf_iters: uint64 = calculate_slot_iters(constants, ips)
                if finished_slot_n == 0:
                    # First block, one empty slot. prior_point is the initial challenge
                    rc_eos_vdf_challenge: bytes32 = constants.FIRST_RC_CHALLENGE
                else:
                    # First block, but have at least two empty slots
                    rc_eos_vdf_challenge: bytes32 = header_block.finished_slots[finished_slot_n - 1][1].get_hash()
            else:
                if finished_slot_n == 0:
                    # No empty slots, so the starting point of VDF is the last reward block. Uses
                    # the same IPS as the previous block, since it's the same slot
                    rc_eos_vdf_challenge: bytes32 = prev_sb.reward_infusion_output
                    rc_eos_vdf_iters = calculate_slot_iters(constants, prev_sb.ips) - calculate_ip_iters(
                        constants, prev_sb.ips, prev_sb.required_iters
                    )
                else:
                    # At least one empty slot, so use previous slot hash. IPS might change because it's a new slot
                    ips: uint64 = get_next_ips(
                        constants, height_to_hash, sub_blocks, header_block.prev_header_hash, True
                    )
                    rc_eos_vdf_challenge: bytes32 = header_block.finished_slots[finished_slot_n - 1][1].get_hash()
                    rc_eos_vdf_iters = calculate_slot_iters(constants, ips)

            target_vdf_info = VDFInfo(
                rc_eos_vdf_challenge,
                ClassgroupElement.get_default_element(),
                rc_eos_vdf_iters,
                reward_slot.end_of_slot_vdf.output,
            )
            if slot_proofs.reward_chain_slot_proof.is_valid(constants, reward_slot.end_of_slot_vdf, target_vdf_info):
                return None, Err.INVALID_RC_EOS_VDF

            # 2j. Check deficit (0 deficit edge case for genesis block)
            if prev_sb is None:
                if reward_slot.deficit != 0:
                    return None, Err.INVALID_DEFICIT
            else:
                curr: SubBlockRecord = prev_sb
                deficit: int = constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1
                while not curr.makes_challenge_block and curr.height > 0:
                    deficit -= 1
                    curr = sub_blocks[curr.prev_block_hash]
                if max(deficit, 0) != reward_slot.deficit:
                    return None, Err.INVALID_DEFICIT

            # 2k. Check made_non_overflow_infusions (False edge case for genesis block)
            if prev_sb is None:
                if reward_slot.made_non_overflow_infusions:
                    return None, Err.INVALID_MADE_NON_OVERFLOW_INFUSIONS
            else:
                if finished_slot_n > 0:
                    if reward_slot.made_non_overflow_infusions:
                        return None, Err.INVALID_MADE_NON_OVERFLOW_INFUSIONS
                else:
                    curr: SubBlockRecord = prev_sb
                    made_non_overflow_infusion: bool = False
                    # Go until the previous slot starts
                    while not curr.first_in_slot and curr.height > 0:
                        if not is_overflow_sub_block(constants, curr.ips, curr.required_iters):
                            made_non_overflow_infusion = True
                        curr = sub_blocks[curr.prev_block_hash]

                    # This is the first sub-block in the previous slot
                    if not is_overflow_sub_block(constants, curr.ips, curr.required_iters):
                        made_non_overflow_infusion = True
                    if made_non_overflow_infusion != reward_slot.made_non_overflow_infusions:
                        return None, Err.INVALID_MADE_NON_OVERFLOW_INFUSIONS

        # 3. Check sub-epoch summary
        # Note that the subepoch summary is the summary of the previous subepoch (not the one that just finished)
        if ses_hash is not None:
            # 3a. Check that genesis block does not have sub-epoch summary
            if prev_sb is None:
                return None, Err.INVALID_SUB_EPOCH_SUMMARY

            finishes_se = finishes_sub_epoch(constants, sub_blocks, header_block.prev_header_hash, False)
            finishes_epoch: bool = finishes_sub_epoch(constants, sub_blocks, header_block.prev_header_hash, True)

            # 3b. Check that we finished a slot and we finished a sub-epoch
            if not new_slot or not finishes_se:
                return None, Err.INVALID_SUB_EPOCH_SUMMARY

            curr = prev_sb
            while curr.sub_epoch_summary_included_hash is None:
                curr = sub_blocks[curr.prev_hash]

            if finishes_epoch:
                next_diff = get_next_difficulty(
                    constants, sub_blocks, height_to_hash, header_block.prev_header_hash, True
                )
                next_ips = get_next_ips(constants, sub_blocks, height_to_hash, header_block.prev_header_hash, True)
            else:
                next_diff = None
                next_ips = None

            # 3c. Check the actual sub-epoch is correct
            expected_sub_epoch_summary = SubEpochSummary(
                curr.sub_epoch_summary_included_hash,
                curr.finished_reward_slot_hashes[-1],
                curr.height % constants.SUB_EPOCH_SUB_BLOCKS,
                next_diff,
                next_ips,
            )
            if expected_sub_epoch_summary.get_hash() != ses_hash:
                return None, Err.INVALID_SUB_EPOCH_SUMMARY
        else:
            # 3d. Check that we don't have to include a sub-epoch summary
            if prev_sb is not None and new_slot:
                finishes = finishes_sub_epoch(constants, sub_blocks, header_block.prev_header_hash, False)
                if finishes:
                    return None, Err.INVALID_SUB_EPOCH_SUMMARY

        # 4. Check proof of space
        q_str: Optional[bytes32] = header_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
            constants,
            header_block.reward_chain_sub_block.challenge_chain_icp_vdf.output.get_hash(),
            header_block.reward_chain_sub_block.challenge_chain_icp_sig,
        )
        if q_str is None:
            return None, Err.INVALID_POSPACE
        if prev_sb is None:
            difficulty: uint64 = uint64(constants.DIFFICULTY_STARTING)
            ips: uint64 = uint64(constants.IPS_STARTING)
        else:
            difficulty = get_next_difficulty(constants, sub_blocks, height_to_hash, prev_sb.header_hash, new_slot)
            ips: uint64 = get_next_ips(constants, sub_blocks, height_to_hash, prev_sb.header_hash, new_slot)
        required_iters: uint64 = calculate_iterations_quality(
            q_str,
            header_block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
        )

        icp_iters: uint64 = calculate_icp_iters(constants, ips, required_iters)
        ip_iters: uint64 = calculate_ip_iters(constants, ips, required_iters)
        slot_iters: uint64 = calculate_slot_iters(constants, ips)
        overflow = is_overflow_sub_block(constants, ips, required_iters)

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
                    if header_block.finished_slots[-1][0].proof_of_space is not None:
                        # New slot with overflow block, where prev slot had challenge block
                        challenge = header_block.finished_slots[-1][0].proof_of_space.challenge_hash
                    else:
                        # New slot with overflow block, where prev slot had no challenge block
                        challenge = header_block.finished_slots[-1][0].end_of_slot_vdf.challenge_hash
                else:
                    # No overflow, new slot with a new challenge
                    challenge = header_block.finished_slots[-1][0].get_hash()
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
            if header_block.weight != uint128(0):
                return None, Err.INVALID_WEIGHT

        # 9. Check total iters
        if prev_sb is None:
            total_iters: uint128 = uint128(
                constants.IPS_STARTING * constants.SLOT_TIME_TARGET * len(header_block.finished_slots)
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
            rc_vdf_challenge: bytes32 = header_block.finished_slots[-1][1].get_hash()
            icp_vdf_iters = icp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        elif new_slot and overflow and len(header_block.finished_slots) > 1:
            # Start from start of prev slot. Rare case of empty prev slot. Includes genesis block after 2 empty slots
            rc_vdf_challenge = header_block.finished_slots[-2][1].get_hash()
            icp_vdf_iters = icp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        elif prev_sb is None:
            # Genesis block case, first challenge
            rc_vdf_challenge = constants.FIRST_CC_CHALLENGE
            icp_vdf_iters = icp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        else:
            # Start from prev block. This is when there is no new slot or if there is a new slot and we overflow
            # but the prev block was is in the same slot (prev slot). This is the normal overflow case.
            rc_vdf_challenge = prev_sb.reward_infusion_output
            icp_vdf_iters = (total_iters - required_iters) + icp_iters - prev_sb.total_iters
            cc_vdf_input = prev_sb.challenge_vdf_output

        # 10. Check reward chain icp proof
        target_vdf_info = VDFInfo(
            rc_vdf_challenge,
            ClassgroupElement.get_default_element(),
            icp_vdf_iters,
            header_block.reward_chain_sub_block.reward_chain_icp_vdf.output,
        )
        if not header_block.reward_chain_icp_proof.is_valid(
            constants, header_block.reward_chain_sub_block.reward_chain_icp_vdf, target_vdf_info
        ):
            return None, Err.INVALID_RC_ICP_VDF

        # 11. Check reward chain icp signature
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            bytes(header_block.reward_chain_sub_block.reward_chain_icp_vdf),
            header_block.reward_chain_sub_block.reward_chain_icp_sig,
        ):
            return None, Err.INVALID_RC_SIGNATURE

        if prev_sb is None:
            cc_vdf_challenge = constants.FIRST_CC_CHALLENGE
        else:
            if new_slot:
                cc_vdf_challenge = header_block.finished_slots[-1][0].get_hash()
            else:
                curr: SubBlockRecord = prev_sb
                while not curr.first_in_slot:
                    curr = sub_blocks[curr.prev_hash]
                cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

        # 12. Check cc icp
        target_vdf_info = VDFInfo(
            cc_vdf_challenge,
            cc_vdf_input,
            icp_vdf_iters,
            header_block.reward_chain_sub_block.challenge_chain_icp_vdf.output,
        )
        if not header_block.challenge_chain_icp_proof.is_valid(
            constants, header_block.reward_chain_sub_block.challenge_chain_icp_vdf, target_vdf_info
        ):
            return None, Err.INVALID_CC_ICP_VDF

        # 13. Check cc icp sig
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            bytes(header_block.reward_chain_sub_block.challenge_chain_icp_vdf.output),
            header_block.reward_chain_sub_block.challenge_chain_icp_sig,
        ):
            return None, Err.INVALID_CC_SIGNATURE

        # 15. Check is_block
        if prev_sb is None:
            if not header_block.foliage_sub_block.is_block:
                return None, Err.INVALID_IS_BLOCK
        else:
            # Finds the previous block
            curr: SubBlockRecord = prev_sb
            while not curr.is_block:
                curr = sub_blocks[curr.prev_hash]

            # The first sub-block to have an icp > the last block's infusion iters, is a block
            if overflow:
                our_icp_total_iters: uint128 = uint128(total_iters - ip_iters + icp_iters - slot_iters)
            else:
                our_icp_total_iters: uint128 = uint128(total_iters - ip_iters + icp_iters)
            if (our_icp_total_iters > curr.total_iters) != header_block.foliage_sub_block.is_block:
                return None, Err.INVALID_IS_BLOCK

        # 16. Check foliage signature by plot key
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            bytes(header_block.foliage_sub_block.signed_data),
            header_block.foliage_sub_block.plot_key_signature,
        ):
            return None, Err.INVALID_PLOT_SIGNATURE

        # 17. Check unfinished reward chain sub block hash
        if (
            header_block.reward_chain_sub_block.get_hash()
            != header_block.foliage_sub_block.signed_data.unfinished_reward_block_hash
        ):
            return None, Err.INVALID_URSB_HASH

        # 18. Check pool target max height
        if (
            header_block.foliage_sub_block.signed_data.pool_target.max_height != 0
            and header_block.foliage_sub_block.signed_data.pool_target.max_height < header_block.height
        ):
            return None, Err.OLD_POOL_TARGET

        # 19. Check pool target signature
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.pool_public_key,
            bytes(header_block.foliage_sub_block.signed_data.pool_target),
            header_block.foliage_sub_block.signed_data.pool_signature,
        ):
            return None, Err.INVALID_POOL_SIGNATURE

        # 20. Check extension data if applicable. None for mainnet.
        # 21. Check if foliage block is present
        if header_block.foliage_sub_block.is_block != (header_block.foliage_block is not None):
            return None, Err.INVALID_FOLIAGE_BLOCK_PRESENCE

        if header_block.foliage_block is not None:
            # 22. Check foliage block hash
            if header_block.foliage_block.get_hash() != header_block.foliage_sub_block.signed_data.foliage_block_hash:
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
        header_block.finished_slots,
        header_block.reward_chain_sub_block.get_unfinished(),
        header_block.challenge_chain_icp_proof,
        header_block.reward_chain_icp_proof,
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
    new_slot: bool = len(header_block.finished_slots) > 0
    if prev_sb is None:
        ips = uint64(constants.IPS_STARTING)
    else:
        ips: uint64 = get_next_ips(constants, sub_blocks, height_to_hash, header_block.prev_header_hash, new_slot)
    ip_iters: uint64 = calculate_ip_iters(constants, ips, required_iters)

    # RC vdf challenge is taken from more recent of (slot start, prev_block)
    if prev_sb is None:
        cc_vdf_output = ClassgroupElement.get_default_element()
        ip_vdf_iters = ip_iters
        if new_slot:
            rc_vdf_challenge = header_block.finished_slots[-1][1].get_hash()
        else:
            rc_vdf_challenge = constants.FIRST_RC_CHALLENGE
    else:
        if new_slot:
            # slot start is more recent
            rc_vdf_challenge = header_block.finished_slots[-1][1].get_hash()
            ip_vdf_iters = ip_iters
            cc_vdf_output = ClassgroupElement.get_default_element()

        else:
            # Prev sb is more recent
            rc_vdf_challenge: bytes32 = prev_sb.reward_infusion_output
            ip_vdf_iters: uint64 = uint64(header_block.reward_chain_sub_block.total_iters - prev_sb.total_iters)
            cc_vdf_output = prev_sb.challenge_vdf_output

    # 26. Check challenge chain infusion point VDF
    if header_block.finished_slots is not None:
        cc_vdf_challenge = header_block.finished_slots[-1][0].get_hash()
    else:
        # Not first sub-block in slot
        if prev_sb is None:
            # Genesis block
            cc_vdf_challenge = constants.FIRST_CC_CHALLENGE
        else:
            # Not genesis block, go back to first sub-block in slot
            curr = prev_sb
            while not curr.makes_challenge_block:
                curr = sub_blocks[curr.prev_hash]
            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

    cc_target_vdf_info = VDFInfo(
        cc_vdf_challenge,
        cc_vdf_output,
        ip_vdf_iters,
        header_block.reward_chain_sub_block.challenge_chain_ip_vdf.output,
    )
    if not header_block.challenge_chain_ip_proof.is_valid(
        constants, header_block.reward_chain_sub_block.challenge_chain_ip_vdf, cc_target_vdf_info
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
        constants, header_block.reward_chain_sub_block.reward_chain_ip_vdf, rc_target_vdf_info
    ):
        return None, Err.INVALID_RC_IP_VDF

    # 28. Check reward block hash
    if header_block.foliage_sub_block.reward_block_hash != header_block.reward_chain_sub_block.get_hash():
        return None, Err.INVALID_REWARD_BLOCK_HASH

    return required_iters, None
