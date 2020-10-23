import logging
from typing import Dict, Optional, List
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
    calculate_infusion_point_iters,
    calculate_infusion_challenge_point_iters,
    calculate_slot_iters,
    calculate_iterations_quality,
)
from src.consensus.infusion import infuse_signature
from src.full_node.difficulty_adjustment import finishes_sub_epoch
from src.full_node.challenge_chain_data import ChallengeChainData
from src.util.hash import std_hash
from src.types.classgroup import ClassgroupElement

log = logging.getLogger(__name__)


# noinspection PyCallByClass
async def validate_unfinished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: UnfinishedHeaderBlock,
    check_filter: bool,
) -> Optional[Err]:
    """
    Validates an unfinished header block. This is a block without the infusion VDFs (unfinished)
    and without transactions and transaction info (header).
    """

    prev_sb: SubBlockRecord = sub_blocks[header_block.prev_header_hash]
    new_slot: bool = len(header_block.finished_slots) > 0

    # 1. Check finished slots
    if not new_slot:
        # Not crossed a slot since previous block
        if header_block.subepoch_summary is not None:
            return Err.NO_END_OF_SLOT_INFO
    else:
        # Finished a slot(s) since previous block
        have_ses_hash: bool = False
        for finished_slot_n, (challenge_slot, reward_slot, slot_proofs) in enumerate(header_block.finished_slots):
            # 1a. check prev slot hash
            if challenge_slot.icp_vdf is not None:
                prev_slot_hash = challenge_slot.icp_vdf.chalenge_hash
            else:
                prev_slot_hash = challenge_slot.end_of_slot_vdf.challenge_hash
            if finished_slot_n == 0:
                curr: SubBlockRecord = prev_sb
                while curr.finished_challenge_slot_hashes is None:
                    curr = sub_blocks[curr.prev_hash]
                assert curr.finished_challenge_slot_hashes is not None
                if not curr.finished_challenge_slot_hashes[-1] != prev_slot_hash:
                    return Err.INVALID_PREV_CHALLENGE_SLOT_HASH
            else:

                if not header_block.finished_slots[finished_slot_n - 1][0].get_hash() == prev_slot_hash:
                    return Err.INVALID_PREV_CHALLENGE_SLOT_HASH

            # 1b. check sub-epoch summary hash
            if challenge_slot.subepoch_summary_hash is not None:
                assert not have_ses_hash
                have_ses_hash = True
                if header_block.subepoch_summary is None:
                    return Err.INVALID_SUB_EPOCH_SUMMARY
                if header_block.subepoch_summary.get_hash() != challenge_slot.subepoch_summary_hash:
                    return Err.INVALID_SUB_EPOCH_SUMMARY_HASH
            if finished_slot_n != 0:
                if challenge_slot.subepoch_summary_hash is not None:
                    return Err.INVALID_SUB_EPOCH_SUMMARY_HASH

            if challenge_slot.proof_of_space is not None:
                # There is a challenge block in this finished slot
                # 1c. Check that there was a challenge block made in the target slot, and find it
                if finished_slot_n != 0:
                    return Err.SHOULD_NOT_MAKE_CHALLENGE_BLOCK
                curr: SubBlockRecord = prev_sb  # prev_sb is guaranteed to be in challenge slot
                while not curr.makes_challenge_block:
                    if curr.finished_challenge_slot_hashes is not None:
                        return Err.SHOULD_NOT_MAKE_CHALLENGE_BLOCK
                    curr = sub_blocks[curr.prev_hash]

                # 1d. Check challenge chain data hash (proof of space, icp output, icp sig, ip output)
                challenge_chain_data_hash = std_hash(
                    bytes(
                        ChallengeChainData(
                            challenge_slot.proof_of_space,
                            challenge_slot.icp_proof_of_time_output,
                            challenge_slot.icp_signature,
                            challenge_slot.ip_proof_of_time_output,
                        )
                    )
                )
                if curr.challenge_chain_data_hash != challenge_chain_data_hash:
                    return Err.INVALID_CHALLENGE_CHAIN_DATA

                # 1e. Check challenge chain end of slot VDF
                ip_iters = calculate_infusion_point_iters(constants, curr.ips, curr.required_iters)
                eos_iters: uint64 = calculate_slot_iters(constants, curr.ips) - ip_iters
                infusion_challenge = infuse_signature(
                    challenge_slot.ip_proof_of_time_output, challenge_slot.icp_signature
                )
                target_vdf_info = VDFInfo(
                    infusion_challenge,
                    ClassgroupElement.get_default_element(),
                    eos_iters,
                    challenge_slot.end_of_slot_vdf.output,
                )
                if slot_proofs.challenge_chain_slot_proof.is_valid(
                    constants, challenge_slot.end_of_slot_vdf, target_vdf_info
                ):
                    return Err.INVALID_CC_EOS_VDF

            else:
                # There are no challenge blocks in this finished_slot tuple (empty slot)
                # 1f. Check that we are not allowed to make a challenge block
                if finished_slot_n == 0:
                    # If finished_slot_n > 0, guaranteed that we cannot make challenge block, so only checks 0
                    curr: SubBlockRecord = prev_sb
                    while curr.finished_challenge_slot_hashes is None:
                        if curr.makes_challenge_block:
                            return Err.SHOULD_MAKE_CHALLENGE_BLOCK
                        curr = sub_blocks[curr.prev_hash]
                    if curr.makes_challenge_block:
                        return Err.SHOULD_MAKE_CHALLENGE_BLOCK

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
                    return Err.INVALID_CC_EOS_VDF

            # 1g. Check challenge slot hash in reward slot
            if reward_slot.challenge_slot_hash != challenge_slot.get_hash_no_ses():
                return Err.INVALID_CHALLENGE_SLOT_HASH_RC

            # 1h. Check end of reward slot VDF
            if finished_slot_n == 0:
                prior_point: bytes32 = prev_sb.reward_infusion_output
                iters = calculate_slot_iters(constants, prev_sb.ips) - calculate_infusion_point_iters(
                    constants, prev_sb.ips, prev_sb.required_iters
                )
            else:
                ips: uint64 = get_next_ips(constants, height_to_hash, sub_blocks, header_block.prev_header_hash, True)
                prior_point: bytes32 = header_block.finished_slots[finished_slot_n - 1][1].get_hash()
                iters = calculate_slot_iters(constants, ips)

            target_vdf_info = VDFInfo(
                prior_point, ClassgroupElement.get_default_element(), iters, reward_slot.end_of_slot_vdf.output,
            )
            if slot_proofs.reward_chain_slot_proof.is_valid(constants, reward_slot.end_of_slot_vdf, target_vdf_info):
                return Err.INVALID_RC_EOS_VDF

            # 1j. Check deficit
            curr: SubBlockRecord = prev_sb
            deficit: int = constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1
            while not curr.makes_challenge_block and curr.height > 0:
                deficit -= 1
                curr = sub_blocks[curr.prev_block_hash]
            if max(deficit, 0) != reward_slot.deficit:
                return Err.INVALID_DEFICIT

            # 1k. Check made_non_overflow_infusions
            if finished_slot_n > 0:
                if reward_slot.made_non_overflow_infusions:
                    return Err.INVALID_MADE_NON_OVERFLOW_INFUSIONS
            else:
                curr: SubBlockRecord = prev_sb
                made_non_overflow_infusion: bool = False
                while not curr.first_in_slot and curr.height > 0:
                    if is_overflow_sub_block(constants, curr.ips, curr.required_iters):
                        made_non_overflow_infusion = True
                    curr = sub_blocks[curr.prev_block_hash]
                if is_overflow_sub_block(constants, curr.ips, curr.required_iters):
                    made_non_overflow_infusion = True
                if made_non_overflow_infusion != reward_slot.made_non_overflow_infusions:
                    return Err.INVALID_MADE_NON_OVERFLOW_INFUSIONS

        # 2. Check sub-epoch summary
        if not have_ses_hash and header_block.subepoch_summary is not None:
            return Err.NO_SUB_EPOCH_SUMMARY_HASH

        # If have_ses_hash, hash has already been validated (subepoch summary guaranteed to not be None)
        # Note that the subepoch summary is the summary of the previous subepoch (not the one that just finished)
        if new_slot and finishes_sub_epoch(constants, sub_blocks, prev_sb.header_hash, False):
            # 2a. If new sub-epoch, sub-epoch summary and hash
            if header_block.subepoch_summary is None or not have_ses_hash:
                return Err.INVALID_SUB_EPOCH_SUMMARY
            curr = prev_sb
            while curr.sub_epoch_summary_included_hash is None:
                curr = sub_blocks[curr.prev_hash]
            # 2b. check prev sub-epoch summary hash
            if curr.sub_epoch_summary_included_hash != header_block.subepoch_summary.prev_subepoch_summary_hash:
                return Err.INVALID_PREV_SUB_EPOCH_SUMMARY_HASH

            # 2c. Check reward chain hash
            if curr.finished_reward_slot_hashes[-1] != header_block.subepoch_summary.reward_chain_hash:
                return Err.INVALID_REWARD_CHAIN_HASH

            # 2d. Check sub-epoch overflow
            if curr.height % constants.SUB_EPOCH_SUB_BLOCKS != header_block.subepoch_summary.num_subblocks_overflow:
                return Err.INVALID_SUB_EPOCH_OVERFLOW

            finishes_epoch: bool = finishes_sub_epoch(constants, sub_blocks, curr.prev_hash, True)
            # 2e. Check difficulty and new ips on new epoch
            if finishes_epoch:
                next_diff = get_next_difficulty(constants, sub_blocks, height_to_hash, curr.prev_hash, True)
                next_ips = get_next_ips(constants, sub_blocks, height_to_hash, curr.prev_hash, True)
                if next_diff != header_block.subepoch_summary.new_difficulty:
                    return Err.INVALID_NEW_DIFFICULTY
                if next_ips != header_block.subepoch_summary.new_ips:
                    return Err.INVALID_NEW_IPS

            # 2f. Check difficulty and new ips not present if not new epoch
            if header_block.subepoch_summary.new_difficulty is not None:
                return Err.INVALID_NEW_DIFFICULTY
            if header_block.subepoch_summary.new_ips is not None:
                return Err.INVALID_NEW_IPS

        else:
            # 2a. If not new sub-epoch, no sub-epoch summary
            if have_ses_hash or header_block.subepoch_summary is not None:
                return Err.INVALID_SUB_EPOCH_SUMMARY

        # 3. Check proof of space
        q_str: Optional[bytes32] = header_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
            constants.NUMBER_ZERO_BITS_CHALLENGE_SIG
        )
        if q_str is None:
            return Err.INVALID_POSPACE
        difficulty = get_next_difficulty(constants, sub_blocks, height_to_hash, prev_sb.header_hash, new_slot)
        required_iters: uint64 = calculate_iterations_quality(
            q_str, header_block.reward_chain_sub_block.proof_of_space.size, difficulty,
        )

        ips: uint64 = get_next_ips(constants, sub_blocks, height_to_hash, prev_sb.header_hash, new_slot)
        icp_iters: uint64 = calculate_infusion_challenge_point_iters(constants, ips, required_iters)
        ip_iters: uint64 = calculate_infusion_point_iters(constants, ips, required_iters)
        slot_iters: uint64 = calculate_slot_iters(constants, ips)
        overflow = is_overflow_sub_block(constants, ips, required_iters)

        # If sub_block state is correct, we should always find a challenge here
        # This computes what the challenge should be for this sub-block
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

        # 4. Check challenge in proof of space is valid
        if challenge != header_block.reward_chain_sub_block.proof_of_space.challenge_hash:
            return Err.INVALID_POSPACE_CHALLENGE

        # 5. Check sub-block height
        if header_block.height != prev_sb.height + 1:
            return Err.INVALID_HEIGHT

        # 6. Check weight
        if header_block.weight != prev_sb.weight + difficulty:
            return Err.INVALID_WEIGHT

        # 7. Check total iters
        prev_sb_iters = calculate_infusion_point_iters(constants, prev_sb.ips, prev_sb.required_iters)
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
            return Err.INVALID_TOTAL_ITERS

        # 8. Check icp challenge (this is checked along with 11 in is_valid method)
        if new_slot and not overflow:
            # Start from start of this slot. Case of no overflow slots.
            prior_point = header_block.finished_slots[-1][1].get_hash()
            icp_vdf_iters = icp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        elif new_slot and overflow and len(header_block.finished_slots) > 1:
            # Start from start of prev slot. Rare case of empty prev slot.
            prior_point = header_block.finished_slots[-2][1].get_hash()
            icp_vdf_iters = icp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        else:
            # Start from prev block. This is when there is no new slot or if there is a new slot and we overflow
            # but the prev block was is in the same slot (prev slot). This is the normal overflow case.
            prior_point = prev_sb.reward_infusion_output
            icp_vdf_iters = (total_iters - required_iters) + icp_iters - prev_sb.total_iters
            cc_vdf_input = prev_sb.challenge_vdf_output

        # 9. Check icp proof
        target_vdf_info = VDFInfo(
            prior_point,
            ClassgroupElement.get_default_element(),
            icp_vdf_iters,
            header_block.reward_chain_sub_block.infusion_challenge_point_vdf.output,
        )
        if not header_block.reward_chain_icp_proof.is_valid(
            constants, header_block.reward_chain_sub_block.infusion_challenge_point_vdf, target_vdf_info
        ):
            return Err.INVALID_RC_ICP_VDF

        # 10. Check icp signature
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            bytes(header_block.reward_chain_sub_block.infusion_challenge_point),
            header_block.reward_chain_sub_block.infusion_challenge_point_sig,
        ):
            return Err.INVALID_RC_SIGNATURE

        # Can only make a challenge block if deficit is zero AND (not overflow or not prev_slot_non_overflow_infusions)
        if new_slot:
            deficit = header_block.finished_slots[-1][1].deficit
            prev_slot_non_overflow_infusions = header_block.finished_slots[-1][1].made_non_overflow_infusions
            cc_vdf_challenge = header_block.finished_slots[-1][0].get_hash()
        else:
            curr: SubBlockRecord = prev_sb
            while not curr.first_in_slot:
                curr = sub_blocks[curr.prev_hash]
            deficit = curr.deficit
            prev_slot_non_overflow_infusions = curr.previous_slot_non_overflow_infusions
            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

        if deficit == 0 and (not overflow or not prev_slot_non_overflow_infusions):
            # 11a. Check cc icp
            target_vdf_info = VDFInfo(
                cc_vdf_challenge, cc_vdf_input, icp_vdf_iters, header_block.challenge_chain_icp_vdf.output,
            )
            if not header_block.challenge_chain_icp_proof.is_valid(
                constants, header_block.challenge_chain_icp_vdf, target_vdf_info
            ):
                return Err.INVALID_CC_ICP_VDF

            # 11b. Check cc icp sig
            if not AugSchemeMPL.verify(
                header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
                bytes(header_block.challenge_chain_icp_vdf.output),
                header_block.challenge_chain_icp_signature,
            ):
                return Err.INVALID_CC_SIGNATURE
        else:
            # 12. Else, check that these are empty
            if (
                header_block.challenge_chain_icp_vdf is not None
                or header_block.challenge_chain_icp_proof is not None
                or header_block.challenge_chain_icp_signature is not None
            ):
                return Err.CANNOT_MAKE_CC_BLOCK

        # 13. Check is_block
        if (total_iters - ip_iters + icp_iters > prev_sb.total_iters) != header_block.foliage_sub_block.is_block:
            return Err.INVALID_IS_BLOCK

        # 14. Check foliage signature by plot key
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            bytes(header_block.foliage_sub_block.signed_data),
            header_block.foliage_sub_block.plot_key_signature,
        ):
            return Err.INVALID_PLOT_SIGNATURE

        # 15. Check unfinished reward chain sub block hash
        if (
            header_block.reward_chain_sub_block.get_hash()
            != header_block.foliage_sub_block.signed_data.unfinished_reward_block_hash
        ):
            return Err.INVALID_URSB_HASH

        # 14. Check pool target max height
        if (
            header_block.foliage_sub_block.signed_data.pool_target.max_height != 0
            and header_block.foliage_sub_block.signed_data.pool_target.max_height < header_block.height
        ):
            return Err.OLD_POOL_TARGET

        # 16. Check pool target signature
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.pool_public_key,
            bytes(header_block.foliage_sub_block.signed_data.pool_target),
            header_block.foliage_sub_block.signed_data.pool_signature,
        ):
            return Err.INVALID_POOL_SIGNATURE

        # 17. Check extension data if applicable. None for mainnet.
        # 18. Check if foliage block is present
        if header_block.foliage_sub_block.is_block != (header_block.foliage_block is not None):
            return Err.INVALID_FOLIAGE_BLOCK_PRESENCE

        if header_block.foliage_block is not None:
            # 19. Check foliage block hash
            if header_block.foliage_block.get_hash() != header_block.foliage_sub_block.signed_data.foliage_block_hash:
                return Err.INVALID_FOLIAGE_BLOCK_HASH

            # 20. Check prev block hash
            if header_block.height == 0:
                if header_block.foliage_block.prev_block_hash != bytes([0] * 32):
                    return Err.INVALID_PREV_BLOCK_HASH
            else:
                curr_sb: SubBlockRecord = prev_sb
                while not curr_sb.is_block:
                    curr_sb = sub_blocks[curr_sb.prev_hash]
                if not header_block.foliage_block.prev_block_hash == curr_sb.header_hash:
                    return Err.INVALID_PREV_BLOCK_HASH

            # 21. The filter hash in the Foliage Block must be the hash of the filter
            if check_filter:
                if header_block.foliage_block.filter_hash != std_hash(header_block.transactions_filter):
                    return Err.INVALID_TRANSACTIONS_FILTER_HASH

            # 22. The timestamp in Foliage Block must comply with the timestamp rules
            if header_block.height > 0:
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
                    return Err.TIMESTAMP_TOO_FAR_IN_PAST
                if header_block.foliage_block.timestamp > int(time.time() + constants.MAX_FUTURE_TIME):
                    return Err.TIMESTAMP_TOO_FAR_IN_FUTURE

        return None  # Valid unfinished header block


async def validate_finished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: HeaderBlock,
    check_filter: bool,
) -> Optional[Err]:
    """
    Fully validates the header of a sub-block. A header block is the same as a full block, but
    without transactions and transaction info.
    """

    unfinished_header_block = UnfinishedHeaderBlock(
        header_block.subepoch_summary,
        header_block.finished_slots,
        header_block.challenge_chain_icp_vdf,
        header_block.challenge_chain_icp_proof,
        header_block.challenge_chain_icp_signature,
        header_block.reward_chain_sub_block.get_unfinished(),
        header_block.reward_chain_icp_proof,
        header_block.foliage_sub_block,
        header_block.foliage_block,
        header_block.transactions_filter,
    )

    validate_unfinished_result: Optional[Err] = await validate_unfinished_header_block(
        constants, sub_blocks, height_to_hash, unfinished_header_block, check_filter
    )

    if validate_unfinished_result is not None:
        return validate_unfinished_result

    prev_sb: SubBlockRecord = sub_blocks[header_block.prev_header_hash]
    new_slot: bool = len(header_block.finished_slots) > 0
    ips: uint64 = get_next_ips(constants, sub_blocks, height_to_hash, header_block.prev_header_hash, new_slot)
    difficulty: uint64 = get_next_difficulty(
        constants, sub_blocks, height_to_hash, header_block.prev_header_hash, new_slot
    )
    q_str: Optional[bytes32] = header_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
        constants.NUMBER_ZERO_BITS_CHALLENGE_SIG
    )
    # TODO: remove redundant verification of PoSpace
    required_iters: uint64 = calculate_iterations_quality(
        q_str, header_block.reward_chain_sub_block.proof_of_space.size, difficulty,
    )
    ip_iters: uint64 = calculate_infusion_point_iters(constants, ips, required_iters)

    # 23. Check reward chain infusion point prev
    # Check from more recent of (slot start, prev_block)
    slot_start: uint128 = header_block.reward_chain_sub_block.total_iters - ip_iters
    if prev_sb.total_iters == min(prev_sb.total_iters, slot_start):
        rc_vdf_challenge: bytes32 = prev_sb.reward_infusion_output
        ip_vdf_iters: uint64 = uint64(header_block.reward_chain_sub_block.total_iters - prev_sb.total_iters)
        cc_vdf_output = prev_sb.challenge_vdf_output
    else:
        assert new_slot
        rc_vdf_challenge = header_block.finished_slots[-1][1].get_hash()
        ip_vdf_iters = ip_iters
        cc_vdf_output = ClassgroupElement.get_default_element()

    # 24. Check challenge chain infusion point VDF
    if header_block.finished_slots is not None:
        cc_vdf_challenge = header_block.finished_slots[-1][0].get_hash()
    else:
        curr = prev_sb
        while not curr.makes_challenge_block:
            curr = sub_blocks[curr.prev_hash]
        cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

    cc_target_vdf_info = VDFInfo(
        cc_vdf_challenge, cc_vdf_output, ip_vdf_iters, header_block.challenge_chain_ip_vdf.output,
    )
    if not header_block.challenge_chain_ip_proof.is_valid(
        constants, header_block.challenge_chain_ip_vdf, cc_target_vdf_info
    ):
        return Err.INVALID_CC_IP_VDF

    # 25. Check reward chain infusion point VDF
    rc_target_vdf_info = VDFInfo(
        rc_vdf_challenge,
        ClassgroupElement.get_default_element(),
        ip_vdf_iters,
        header_block.reward_chain_sub_block.infusion_challenge_point_vdf.output,
    )
    if not header_block.reward_chain_ip_proof.is_valid(constants, header_block.reward_chain_ip_vdf, rc_target_vdf_info):
        return Err.INVALID_RC_IP_VDF

    # 26. Check reward block hash
    if header_block.foliage_sub_block.reward_block_hash != header_block.reward_chain_sub_block.get_hash():
        return Err.INVALID_REWARD_BLOCK_HASH

    return None
