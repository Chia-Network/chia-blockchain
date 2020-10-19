import logging
from typing import Dict, Optional

from src.consensus.constants import ConsensusConstants
from src.types.sized_bytes import bytes32
from src.util.errors import Err
from src.util.ints import uint32, uint64
from src.types.unfinished_header_block import UnfinishedHeaderBlock
from src.full_node.sub_block_record import SubBlockRecord
from src.full_node.difficulty_adjustment import get_next_slot_iters

log = logging.getLogger(__name__)


async def validate_unfinished_header_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    header_block: UnfinishedHeaderBlock,
) -> Optional[Err]:
    """
    Validates an unfinished header block.
    """
    prev_sb: SubBlockRecord = sub_blocks[header_block.prev_header_hash]

    slot_iters: uint64 = get_next_slot_iters(header_block.prev_header_hash)
    challenge: Optional[bytes32] = None

    # 1. Check finished slots
    if len(header_block.finished_slots) == 0:
        if header_block.subepoch_summary is not None:
            return Err.NO_END_OF_SLOT_INFO
        ips: uint64 = prev_sb.ips
        slot_iters = constants.SLOT_TIME_TARGET * ips
        extra_iters = int(constants.EXTRA_ITERS_TIME_TARGET * int(ips))
        if (
            header_block.reward_chain_sub_block.infusion_challenge_point.number_of_iterations + extra_iters
            >= slot_iters
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

            if challenge_slot.proof_of_space is not None:
                # 1c. Check that we are allowed to make a challenge block
                if finished_slot_n != 0:
                    return Err.SHOULD_NOT_MAKE_CHALLENGE_BLOCK
                curr: SubBlockRecord = prev_sb
                while not curr.first_block_in_challenge_slot:
                    if curr.finished_challenge_slot_hash is not None:
                        return Err.SHOULD_NOT_MAKE_CHALLENGE_BLOCK
                    curr = sub_blocks[curr.prev_hash]

                # 1d. Check challenge chain pos hash
                if curr.challenge_chain_pos_hash != challenge_slot.proof_of_space.get_hash():
                    return Err.INVALID_CHALLENGE_CHAIN_POS_EOS

                if challenge_slot.icp_proof_of_time_output != slot_proofs.challenge_chain_icp_proof.

            else:
                # 1j. Check that we are not allowed to make a challenge block
                if finished_slot_n == 0:
                    # If finished_slot_n > 0, guaranteed that we cannot make challenge block
                    curr: SubBlockRecord = prev_sb
                    while curr.finished_challenge_slot_hash is None:
                        if curr.first_block_in_challenge_slot:
                            return Err.SHOULD_MAKE_CHALLENGE_BLOCK
                        curr = sub_blocks[curr.prev_hash]
                    if curr.first_block_in_challenge_slot:
                        return Err.SHOULD_MAKE_CHALLENGE_BLOCK

        if not have_ses_hash and header_block.subepoch_summary is not None:
            return Err.NO_SUB_EPOCH_SUMMARY_HASH
