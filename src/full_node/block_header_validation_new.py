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
from src.types.proof_of_time import validate_composite_proof_of_time
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

log = logging.getLogger(__name__)


async def validate_unfinished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: UnfinishedHeaderBlock,
) -> Optional[Err]:
    """
    Validates an unfinished header block. This is a block without the infusion VDFs (unfinished)
    and without transactions and transaction info (header).
    """

    prev_sb: SubBlockRecord = sub_blocks[header_block.prev_header_hash]
    challenge: Optional[bytes32] = None
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
            if finished_slot_n == 0:
                curr: SubBlockRecord = prev_sb
                while curr.finished_challenge_slot_hashes is None:
                    curr = sub_blocks[curr.prev_hash]
                if not curr.finished_challenge_slot_hashes[-1] != challenge_slot.prev_slot_hash:
                    return Err.INVALID_PREV_CHALLENGE_SLOT_HASH
            else:
                if not header_block.finished_slots[finished_slot_n - 1][0].get_hash() == challenge_slot.prev_slot_hash:
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
                # 1c. Check that we are allowed to make a challenge block
                if finished_slot_n != 0:
                    return Err.SHOULD_NOT_MAKE_CHALLENGE_BLOCK
                curr: SubBlockRecord = prev_sb
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
                infusion_challenge = infuse_signature(
                    challenge_slot.ip_proof_of_time_output, challenge_slot.icp_signature
                )
                if not validate_composite_proof_of_time(
                    constants,
                    infusion_challenge,
                    calculate_slot_iters(constants, curr.ips) - ip_iters,
                    challenge_slot.end_of_slot_proof_of_time_output,
                    slot_proofs.challenge_chain_slot_proof,
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
                if not validate_composite_proof_of_time(
                    constants,
                    challenge_slot.prev_slot_hash,
                    calculate_slot_iters(constants, ips_empty_slots),
                    challenge_slot.end_of_slot_proof_of_time_output,
                    slot_proofs.challenge_chain_slot_proof,
                ):
                    return Err.INVALID_CC_EOS_VDF

            # 1g. Check challenge slot hash in reward slot
            if reward_slot.challenge_slot_hash != challenge_slot.get_hash_no_ses():
                return Err.INVALID_CHALLENGE_SLOT_HASH_RC

            # 1h. Check prior point
            if finished_slot_n == 0:
                prior_point: bytes32 = prev_sb.reward_infusion_output
                iters = calculate_slot_iters(constants, prev_sb.ips) - calculate_infusion_point_iters(
                    constants, prev_sb.ips, prev_sb.required_iters
                )
            else:
                ips: uint64 = get_next_ips(constants, height_to_hash, sub_blocks, header_block.prev_header_hash, True)
                prior_point: bytes32 = header_block.finished_slots[finished_slot_n - 1][1].get_hash()
                iters = calculate_slot_iters(constants, ips)

            if prior_point != reward_slot.prior_point:
                return Err.INVALID_PRIOR_POINT_RC

            # 1i. Check end of reward slot VDF
            if not validate_composite_proof_of_time(
                constants,
                prior_point,
                iters,
                reward_slot.end_of_slot_output,
                slot_proofs.reward_chain_slot_proof,
            ):
                return Err.INVALID_RC_EOS_VDF

            # 1j. Check deficit
            curr: SubBlockRecord = prev_sb
            deficit: int = constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1
            while not curr.makes_challenge_block and curr.height > 0:
                deficit -= 1
                curr = sub_blocks[curr.prev_block_hash]
            if max(deficit, 0) != reward_slot.deficit:
                return Err.INVALID_DEFICIT

        # 2. Check sub-epoch summary
        if not have_ses_hash and header_block.subepoch_summary is not None:
            return Err.NO_SUB_EPOCH_SUMMARY_HASH

        # If have_ses_hash, hash has already been validated (subepoch summary guaranteed to not be None)
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
            if header_block.finished_slots[0][1].get_hash() != header_block.subepoch_summary.reward_chain_hash:
                return Err.INVALID_REWARD_CHAIN_HASH

            # 2d. Check sub-epoch overflow
            if (
                header_block.height % constants.SUB_EPOCH_SUB_BLOCKS
                != header_block.subepoch_summary.num_subblocks_overflow
            ):
                return Err.INVALID_SUB_EPOCH_OVERFLOW

            finishes_epoch: bool = finishes_sub_epoch(constants, sub_blocks, prev_sb.header_hash, True)
            # 2e. Check difficulty and new ips on new epoch
            if finishes_epoch:
                next_diff = get_next_difficulty(constants, sub_blocks, height_to_hash, prev_sb.header_hash, True)
                next_ips = get_next_ips(constants, sub_blocks, height_to_hash, prev_sb.header_hash, True)
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
        required_iters: uint64 = calculate_iterations_quality(
            q_str,
            header_block.reward_chain_sub_block.proof_of_space.size,
        )

        ips: uint64 = get_next_ips(constants, sub_blocks, height_to_hash, prev_sb.header_hash, new_slot)
        icp_iters: uint64 = calculate_infusion_challenge_point_iters(constants, ips, required_iters)
        ip_iters: uint64 = calculate_infusion_point_iters(constants, ips, required_iters)
        slot_iters: uint64 = calculate_slot_iters(constants, ips)
        overflow = is_overflow_sub_block(constants, ips, required_iters)
        difficulty = get_next_difficulty(constants, sub_blocks, height_to_hash, prev_sb.header_hash, new_slot)

        # If sub_block state is correct, we should always find a challenge here
        if overflow:
            # Overflow infusion, so get the second to last challenge
            challenges_to_look_for = 2
        else:
            challenges_to_look_for = 1
        seen_challenges = 0
        curr: SubBlockRecord = prev_sb
        while seen_challenges < challenges_to_look_for:
            if curr.finished_challenge_slot_hashes is not None:
                seen_challenges += 1
                challenge = curr.finished_challenge_slot_hashes[-1]
            curr = sub_blocks[curr.prev_hash]
        assert challenge is not None

        # 4. Check challenge in proof of space is valid
        if challenge != header_block.reward_chain_sub_block.proof_of_space.challenge_hash:
            return Err.INVALID_POSPACE_CHALLENGE

        # We can only make a challenge block if deficit is zero
        makes_challenge_block: bool = new_slot and header_block.finished_slots[0][1].deficit == 0

        if makes_challenge_block:
            # 5a. Check cc icp
            cc_icp_challenge: bytes32 = header_block.finished_slots[-1][0].get_hash()
            output: bytes32 = header_block.reward_chain_sub_block.infusion_point
            if not await validate_composite_proof_of_time(
                constants, cc_icp_challenge, icp_iters, output, header_block.challenge_chain_icp_pot
            ):
                return Err.INVALID_CC_ICP_VDF

            # 5b. Check cc icp sig
            if not AugSchemeMPL.verify(
                header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
                bytes(header_block.challenge_chain_icp_pot[-1].output),
                header_block.challenge_chain_icp_signature,
            ):
                return Err.INVALID_CC_SIGNATURE
        else:
            # 6. Else, check that these are empty
            if (
                header_block.challenge_chain_icp_pot is not None
                or header_block.challenge_chain_icp_signature is not None
            ):
                return Err.CANNOT_MAKE_CC_BLOCK

        # 7. Check sub-block height
        if header_block.height != prev_sb.height + 1:
            return Err.INVALID_HEIGHT

        # 8. Check weight
        if header_block.weight != prev_sb.weight + difficulty:
            return Err.INVALID_WEIGHT

        # 9. Check total iters
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

        # 10. Check icp_prev_ip
        if new_slot and not overflow:
            # Start from start of this slot. Case of no overflow slots.
            if header_block.reward_chain_sub_block.icp_prev_ip != header_block.finished_slots[-1][1].get_hash():
                return Err.INVALID_RC_ICP_PREV_IP
        elif new_slot and overflow and len(header_block.finished_slots) > 1:
            # Start from start of prev slot. Rare case of empty prev slot.
            if header_block.reward_chain_sub_block.icp_prev_ip != header_block.finished_slots[-2][1].get_hash():
                return Err.INVALID_RC_ICP_PREV_IP
        else:
            # Start from prev block. This is when there is no new slot or if there is a new slot and we overflow
            # but the prev block was is in the same slot (prev slot). This is the normal overflow case.
            if header_block.reward_chain_sub_block.icp_prev_ip != prev_sb.reward_infusion_output:
                return Err.INVALID_RC_ICP_PREV_IP

        # 11. Check icp
        if not await validate_composite_proof_of_time(
            constants,
            header_block.reward_chain_sub_block.icp_prev_ip,
            icp_iters,
            header_block.reward_chain_sub_block.infusion_challenge_point,
            header_block.reward_chain_icp_pot,
        ):
            return Err.INVALID_RC_ICP_VDF

        # 12. Check icp signature
        if not AugSchemeMPL.verify(
            header_block.reward_chain_sub_block.proof_of_space.plot_public_key,
            bytes(header_block.reward_chain_sub_block.infusion_challenge_point),
            header_block.reward_chain_sub_block.infusion_challenge_point_sig,
        ):
            return Err.INVALID_RC_SIGNATURE

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
) -> Optional[Err]:
    """
    Fully validates the header of a sub-block. A header block is the same as a full block, but
    without transactions and transaction info.
    """

    unfinished_header_block = UnfinishedHeaderBlock(
        header_block.subepoch_summary,
        header_block.finished_slots,
        header_block.challenge_chain_icp_pot,
        header_block.challenge_chain_icp_signature,
        header_block.reward_chain_sub_block.get_unfinished(),
        header_block.reward_chain_icp_pot,
        header_block.foliage_sub_block,
        header_block.foliage_block,
        header_block.transactions_filter,
    )
    validate_unfinished_result: Optional[Err] = await validate_unfinished_header_block(
        constants, sub_blocks, height_to_hash, unfinished_header_block
    )

    if validate_unfinished_result is not None:
        return validate_unfinished_result

    prev_sb: SubBlockRecord = sub_blocks[header_block.prev_header_hash]
    new_slot: bool = len(header_block.finished_slots) > 0
    ips: uint64 = get_next_ips(constants, sub_blocks, height_to_hash, header_block.prev_header_hash, new_slot)
    q_str: Optional[bytes32] = header_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
        constants.NUMBER_ZERO_BITS_CHALLENGE_SIG
    )
    # TODO: remove redundant verification of PoSpace
    required_iters: uint64 = calculate_iterations_quality(
        q_str,
        header_block.reward_chain_sub_block.proof_of_space.size,
    )
    icp_iters: uint64 = calculate_infusion_challenge_point_iters(constants, ips, required_iters)
    ip_iters: uint64 = calculate_infusion_point_iters(constants, ips, required_iters)

    makes_challenge_block: bool = new_slot and header_block.finished_slots[0][1].deficit == 0
    if makes_challenge_block:
        # 23. Check challenge chain infusion point VDF
        cc_vdf_challenge: bytes32 = header_block.finished_slots[-1][0].get_hash()
        if not validate_composite_proof_of_time(
            constants,
            cc_vdf_challenge,
            ip_iters,
            header_block.challenge_chain_ip_pot[-1].output,
            header_block.challenge_chain_ip_pot,
        ):
            return Err.INVALID_CC_IP_VDF

    else:
        if header_block.challenge_chain_ip_pot:
            return Err.IP_SHOULD_BE_NONE

    # 24. Check reward chain infusion point prev
    # Check from more recent of (slot start, ICP, prev_block)
    slot_start: uint128 = header_block.reward_chain_sub_block.total_iters - ip_iters
    icp: uint128 = slot_start + icp_iters
    if prev_sb.total_iters == min(prev_sb.total_iters, slot_start, icp):
        rc_vdf_challenge: bytes32 = prev_sb.reward_infusion_output
    elif icp == min(prev_sb.total_iters, slot_start, icp):
        rc_vdf_challenge = header_block.reward_chain_sub_block.infusion_challenge_point.get_hash()
    else:
        if new_slot:
            rc_vdf_challenge = header_block.finished_slots[-1][1].get_hash()
        else:
            curr = prev_sb
            while curr.finished_challenge_slot_hashes is None:
                curr = sub_blocks[curr.prev_hash]
            rc_vdf_challenge = curr.finished_reward_slot_hashes[-1]

    # 25. Check reward chain infusion point VDF
    if not validate_composite_proof_of_time(
        constants,
        rc_vdf_challenge,
        ip_iters,
        header_block.reward_chain_ip_pot[-1].output,
        header_block.reward_chain_ip_pot,
    ):
        return Err.INVALID_CC_IP_VDF

    # 26. Check reward block hash
    if header_block.foliage_sub_block.reward_block_hash != header_block.reward_chain_sub_block.get_hash():
        return Err.INVALID_REWARD_BLOCK_HASH

    return None
