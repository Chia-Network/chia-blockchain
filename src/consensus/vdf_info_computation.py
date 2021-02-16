from typing import List, Optional

from src.consensus.blockchain_interface import BlockchainInterface
from src.consensus.constants import ConsensusConstants
from src.consensus.block_record import BlockRecord
from src.types.blockchain_format.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint128, uint64


def get_signage_point_vdf_info(
    constants: ConsensusConstants,
    finished_sub_slots: List[EndOfSubSlotBundle],
    overflow: bool,
    prev_b: Optional[BlockRecord],
    blocks: BlockchainInterface,
    sp_total_iters: uint128,
    sp_iters: uint64,
):
    """
    Returns the following information, for the VDF of the signage point at sp_total_iters.
    cc and rc challenge hash
    cc and rc input
    cc and rc iterations
    """

    new_sub_slot: bool = len(finished_sub_slots) > 0
    genesis_block: bool = prev_b is None

    if new_sub_slot and not overflow:
        # Case 1: start from start of this slot. Case of no overflow slots. Also includes genesis block after empty
        # slot(s), but not overflowing
        rc_vdf_challenge: bytes32 = finished_sub_slots[-1].reward_chain.get_hash()
        cc_vdf_challenge = finished_sub_slots[-1].challenge_chain.get_hash()
        sp_vdf_iters = sp_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
    elif new_sub_slot and overflow and len(finished_sub_slots) > 1:
        # Case 2: start from start of prev slot. This is a rare case of empty prev slot. Includes genesis block after
        # 2 empty slots
        rc_vdf_challenge = finished_sub_slots[-2].reward_chain.get_hash()
        cc_vdf_challenge = finished_sub_slots[-2].challenge_chain.get_hash()
        sp_vdf_iters = sp_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
    elif genesis_block:
        # Case 3: Genesis block case, first challenge
        rc_vdf_challenge = constants.GENESIS_CHALLENGE
        cc_vdf_challenge = constants.GENESIS_CHALLENGE
        sp_vdf_iters = sp_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
    elif new_sub_slot and overflow and len(finished_sub_slots) == 1:
        # Case 4: Starting at prev will put us in the previous, sub-slot, since case 2 handled more empty slots
        assert prev_b is not None
        curr: BlockRecord = prev_b
        while not curr.first_in_sub_slot and curr.total_iters > sp_total_iters:
            curr = blocks.block_record(curr.prev_hash)
        if curr.total_iters < sp_total_iters:
            sp_vdf_iters = uint64(sp_total_iters - curr.total_iters)
            cc_vdf_input = curr.challenge_vdf_output
            rc_vdf_challenge = curr.reward_infusion_new_challenge
        else:
            assert curr.finished_reward_slot_hashes is not None
            sp_vdf_iters = sp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
            rc_vdf_challenge = curr.finished_reward_slot_hashes[-1]

        while not curr.first_in_sub_slot:
            curr = blocks.block_record(curr.prev_hash)
        assert curr.finished_challenge_slot_hashes is not None
        cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]
    elif not new_sub_slot and overflow:
        # Case 5: prev is in the same sub slot and also overflow. Starting at prev does not skip any sub slots
        assert prev_b is not None
        curr = prev_b

        # Collects the last two finished slots
        if curr.first_in_sub_slot:
            assert curr.finished_challenge_slot_hashes is not None
            assert curr.finished_reward_slot_hashes is not None
            found_sub_slots = list(
                reversed(
                    list(
                        zip(
                            curr.finished_challenge_slot_hashes,
                            curr.finished_reward_slot_hashes,
                        )
                    )
                )
            )
        else:
            found_sub_slots = []
        sp_pre_sb: Optional[BlockRecord] = None
        while len(found_sub_slots) < 2 and curr.height > 0:
            if sp_pre_sb is None and curr.total_iters < sp_total_iters:
                sp_pre_sb = curr
            curr = blocks.block_record(curr.prev_hash)
            if curr.first_in_sub_slot:
                assert curr.finished_challenge_slot_hashes is not None
                assert curr.finished_reward_slot_hashes is not None
                found_sub_slots += list(
                    reversed(
                        list(
                            zip(
                                curr.finished_challenge_slot_hashes,
                                curr.finished_reward_slot_hashes,
                            )
                        )
                    )
                )
        if sp_pre_sb is None and curr.total_iters < sp_total_iters:
            sp_pre_sb = curr
        if sp_pre_sb is not None:
            sp_vdf_iters = uint64(sp_total_iters - sp_pre_sb.total_iters)
            cc_vdf_input = sp_pre_sb.challenge_vdf_output
            rc_vdf_challenge = sp_pre_sb.reward_infusion_new_challenge
        else:
            sp_vdf_iters = sp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
            rc_vdf_challenge = found_sub_slots[1][1]
        cc_vdf_challenge = found_sub_slots[1][0]

    elif not new_sub_slot and not overflow:
        # Case 6: prev is in the same sub slot. Starting at prev does not skip any sub slots. We do not need
        # to go back another sub slot, because it's not overflow, so the VDF to signage point is this sub-slot.
        assert prev_b is not None
        curr = prev_b
        while not curr.first_in_sub_slot and curr.total_iters > sp_total_iters:
            curr = blocks.block_record(curr.prev_hash)
        if curr.total_iters < sp_total_iters:
            sp_vdf_iters = uint64(sp_total_iters - curr.total_iters)
            cc_vdf_input = curr.challenge_vdf_output
            rc_vdf_challenge = curr.reward_infusion_new_challenge
        else:
            assert curr.finished_reward_slot_hashes is not None
            sp_vdf_iters = sp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
            rc_vdf_challenge = curr.finished_reward_slot_hashes[-1]

        while not curr.first_in_sub_slot:
            curr = blocks.block_record(curr.prev_hash)
        assert curr.finished_challenge_slot_hashes is not None
        cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]
    else:
        # All cases are handled above
        assert False

    return (
        cc_vdf_challenge,
        rc_vdf_challenge,
        cc_vdf_input,
        ClassgroupElement.get_default_element(),
        sp_vdf_iters,
        sp_vdf_iters,
    )
