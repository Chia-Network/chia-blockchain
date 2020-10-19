import logging
from typing import Dict, Optional

from src.consensus.constants import ConsensusConstants
from src.types.sized_bytes import bytes32
from src.util.errors import Err
from src.util.ints import uint32, uint64
from src.types.unfinished_header_block import UnfinishedHeaderBlock
from src.full_node.sub_block_record import SubBlockRecord
from src.full_node.difficulty_adjustment import get_next_ips
from src.types.proof_of_time import validate_composite_proof_of_time
from src.consensus.pot_iterations import calculate_infusion_point_iters, calculate_slot_iters
from src.consensus.infusion import infuse_signature
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

    # 1. Check finished slots
    if len(header_block.finished_slots) == 0:
        # Not crossed a slot since previous block. Gets the challenge
        if header_block.subepoch_summary is not None:
            return Err.NO_END_OF_SLOT_INFO
        ips: uint64 = prev_sb.ips
        slot_iters_same = constants.SLOT_TIME_TARGET * ips
        extra_iters = int(constants.EXTRA_ITERS_TIME_TARGET * int(ips))
        if (
            header_block.reward_chain_sub_block.infusion_challenge_point.number_of_iterations + extra_iters
            >= slot_iters_same
        ):
            # Overflow infusion, so get the second to last challenge
            challenges_to_look_for = 2
        else:
            challenges_to_look_for = 1
        seen_challenges = 0
        curr: SubBlockRecord = prev_sb
        while seen_challenges < challenges_to_look_for:
            if curr.finished_challenge_slot_hash is not None:
                seen_challenges += 1
                challenge = curr.finished_challenge_slot_hash
            curr = sub_blocks[curr.prev_hash]

        # If sub_block state is correct, we should always find a challenge here
        assert challenge is not None
    else:
        # Finished a slot(s) since previous block
        have_ses_hash: bool = False
        for finished_slot_n, (challenge_slot, reward_slot, slot_proofs) in enumerate(header_block.finished_slots):
            # 1a. check prev slot hash
            if finished_slot_n == 0:
                seen_challenges = 0
                curr: SubBlockRecord = prev_sb
                while curr.finished_challenge_slot_hash is None:
                    curr = sub_blocks[curr.prev_hash]
                if not curr.finished_challenge_slot_hash != challenge_slot.prev_slot_hash:
                    return Err.INVALID_PREV_CHALLENGE_SLOT_HASH
            else:
                if not header_block.finished_slots[finished_slot_n - 1][0].get_hash() == challenge_slot.prev_slot_hash:
                    return Err.INVALID_PREV_CHALLENGE_SLOT_HASH

            # 1b. check sub-epoch summary hash
            if challenge_slot.subepoch_summary_hash is not None:
                assert not have_ses_hash
                have_ses_hash = True
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
                    if curr.finished_challenge_slot_hash is not None:
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
                    while curr.finished_challenge_slot_hash is None:
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
            if reward_slot.challenge_slot_hash != challenge_slot.get_hash():
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
            if deficit != reward_slot.deficit:
                return Err.INVALID_DEFICIT

        # 2. Check sub-epoch summary
        if not have_ses_hash and header_block.subepoch_summary is not None:
            return Err.NO_SUB_EPOCH_SUMMARY_HASH
