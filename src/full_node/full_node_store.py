import logging
from typing import Dict, List, Optional, Tuple

from src.consensus.constants import ConsensusConstants
from src.full_node.signage_point import SignagePoint
from src.full_node.sub_block_record import SubBlockRecord
from src.protocols import timelord_protocol
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.types.unfinished_block import UnfinishedBlock
from src.types.vdf import VDFInfo
from src.util.ints import uint32, uint8, uint64, uint128

log = logging.getLogger(__name__)


class FullNodeStore:
    constants: ConsensusConstants

    # Blocks which we have created, but don't have plot signatures yet, so not yet "unfinished blocks"
    candidate_blocks: Dict[bytes32, UnfinishedBlock] = {}

    # Header hashes of unfinished blocks that we have seen recently
    seen_unfinished_blocks: set = set()

    # Blocks which we have received but our blockchain does not reach, old ones are cleared
    disconnected_blocks: Dict[bytes32, FullBlock] = {}

    # Unfinished blocks, keyed from reward hash
    unfinished_blocks: Dict[bytes32, UnfinishedBlock] = {}

    # Finished slots and sps from the peak's slot onwards
    # We store all 32 SPs for each slot, starting as 32 Nones and filling them as we go
    # Also stores the total iters at the end of slot
    # For the first sub-slot, EndOfSlotBundle is None
    finished_sub_slots: List[Tuple[Optional[EndOfSubSlotBundle], Dict[uint8, List[SignagePoint]], uint128]] = []

    # These caches maintain objects which depend on infused sub-blocks in the reward chain, that we
    # might receive before the sub-blocks themselves. The dict keys are the reward chain challenge hashes.

    # End of slots which depend on infusions that we don't have
    future_eos_cache: Dict[bytes32, List[EndOfSubSlotBundle]] = {}

    # Signage points which depend on infusions that we don't have
    future_sp_cache: Dict[bytes32, List[SignagePoint]] = {}

    # Infusion point VDFs which depend on infusions that we don't have
    future_ip_cache: Dict[bytes32, List[timelord_protocol.NewInfusionPointVDF]] = {}

    @classmethod
    async def create(cls, constants: ConsensusConstants):
        self = cls()
        self.constants = constants
        self.clear_slots()
        self.initialize_genesis_sub_slot()
        return self

    def add_candidate_block(
        self,
        quality_string: bytes32,
        unfinished_block: UnfinishedBlock,
    ):
        self.candidate_blocks[quality_string] = unfinished_block

    def get_candidate_block(self, quality_string: bytes32) -> Optional[UnfinishedBlock]:
        return self.candidate_blocks.get(quality_string, None)

    def clear_candidate_blocks_below(self, height: uint32) -> None:
        del_keys = []
        for key, value in self.candidate_blocks.items():
            if value[4] < height:
                del_keys.append(key)
        for key in del_keys:
            try:
                del self.candidate_blocks[key]
            except KeyError:
                pass

    def seen_unfinished_block(self, temp_header_hash: bytes32) -> bool:
        if temp_header_hash in self.seen_unfinished_blocks:
            return True
        self.seen_unfinished_blocks.add(temp_header_hash)
        return False

    def clear_seen_unfinished_blocks(self) -> None:
        self.seen_unfinished_blocks.clear()

    def add_disconnected_block(self, block: FullBlock) -> None:
        self.disconnected_blocks[block.header_hash] = block

    def get_disconnected_block_by_prev(self, prev_header_hash: bytes32) -> Optional[FullBlock]:
        for _, block in self.disconnected_blocks.items():
            if block.prev_header_hash == prev_header_hash:
                return block
        return None

    def get_disconnected_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.disconnected_blocks.get(header_hash, None)

    def clear_disconnected_blocks_below(self, height: uint32) -> None:
        for key in list(self.disconnected_blocks.keys()):
            if self.disconnected_blocks[key].height < height:
                del self.disconnected_blocks[key]

    def add_unfinished_block(self, unfinished_block: UnfinishedBlock) -> None:
        self.unfinished_blocks[unfinished_block.reward_chain_sub_block.get_hash()] = unfinished_block

    def get_unfinished_block(self, unfinished_reward_hash: bytes32) -> Optional[UnfinishedBlock]:
        return self.unfinished_blocks.get(unfinished_reward_hash, None)

    def get_unfinished_blocks(self) -> Dict[bytes32, UnfinishedBlock]:
        return self.unfinished_blocks

    def clear_unfinished_blocks_below(self, height: uint32) -> None:
        for partial_reward_hash, unfinished_block in self.unfinished_blocks.items():
            if unfinished_block.height < height:
                del self.unfinished_blocks[partial_reward_hash]

    def remove_unfinished_block(self, partial_reward_hash: bytes32):
        if partial_reward_hash in self.unfinished_blocks:
            del self.unfinished_blocks[partial_reward_hash]

    def add_to_future_ip(self, infusion_point: timelord_protocol.NewInfusionPointVDF):
        ch: bytes32 = infusion_point.reward_chain_ip_vdf.challenge
        if ch not in self.future_ip_cache:
            self.future_ip_cache[ch] = []
        self.future_ip_cache[ch].append(infusion_point)

    def get_future_ip(self, rc_challenge_hash: bytes32) -> List[timelord_protocol.NewInfusionPointVDF]:
        return self.future_ip_cache.get(rc_challenge_hash, [])

    def clear_slots(self):
        self.finished_sub_slots.clear()

    def get_sub_slot(self, challenge_hash: bytes32) -> Optional[Tuple[EndOfSubSlotBundle, int, uint128]]:
        for index, (sub_slot, _, total_iters) in enumerate(self.finished_sub_slots):
            if sub_slot is not None and sub_slot.challenge_chain.get_hash() == challenge_hash:
                return sub_slot, index, total_iters
        return None

    def initialize_genesis_sub_slot(self):
        self.clear_slots()
        self.finished_sub_slots = [(None, {}, uint128(0))]

    def new_finished_sub_slot(
        self, eos: EndOfSubSlotBundle, sub_blocks: Dict[bytes32, SubBlockRecord], peak: Optional[SubBlockRecord]
    ) -> bool:
        """
        Returns true if finished slot successfully added.
        TODO: do full validation here
        """

        if len(self.finished_sub_slots) == 0:
            return False

        last_slot, _, last_slot_iters = self.finished_sub_slots[-1]
        last_slot_ch = (
            last_slot.challenge_chain.get_hash() if last_slot is not None else self.constants.FIRST_CC_CHALLENGE
        )
        last_slot_rc_hash = (
            last_slot.reward_chain_chain.get_hash() if last_slot is not None else self.constants.FIRST_RC_CHALLENGE
        )

        if eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge != last_slot_ch:
            # This slot does not append to our next slot
            # This prevent other peers from appending fake VDFs to our cache
            return False

        if not eos.proofs.challenge_chain_slot_proof.is_valid(
            self.constants, eos.challenge_chain.challenge_chain_end_of_slot_vdf
        ):
            return False
        if not eos.proofs.reward_chain_slot_proof.is_valid(self.constants, eos.reward_chain.end_of_slot_vdf):
            return False
        if eos.infused_challenge_chain is not None:
            if not eos.proofs.infused_challenge_chain_slot_proof.is_valid(
                self.constants, eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
            ):
                return False

        total_iters = last_slot_iters + eos.challenge_chain.challenge_chain_end_of_slot_vdf.number_of_iterations

        if peak is not None and peak.total_iters > last_slot_iters:
            # Peak is in this slot
            rc_challenge = eos.reward_chain.end_of_slot_vdf.challenge
            if peak.reward_infusion_new_challenge != rc_challenge:
                # We don't have this challenge hash yet
                if rc_challenge not in self.future_eos_cache:
                    self.future_eos_cache[rc_challenge] = []
                self.future_eos_cache[rc_challenge].append(eos)
                return False
            if peak.total_iters + eos.reward_chain.end_of_slot_vdf.number_of_iterations != total_iters:
                return False

            if peak.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                curr = peak
                while not curr.first_in_sub_slot and not curr.is_challenge_sub_block(self.constants):
                    curr = sub_blocks[curr.prev_hash]

                if curr.is_challenge_sub_block(self.constants):
                    icc_start_challenge_hash = curr.challenge_block_info_hash
                else:
                    icc_start_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
                if peak.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    if (
                        eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge
                        != icc_start_challenge_hash
                    ):
                        return False
        else:
            # Empty slot after the peak
            if eos.reward_chain.end_of_slot_vdf.challenge != last_slot_rc_hash:
                return False

            if (
                last_slot is not None
                and last_slot.reward_chain.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
            ):
                # Have infused challenge chain that must be verified
                if (
                    eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge
                    != last_slot.infused_challenge_chain.get_hash()
                ):
                    return False

        self.finished_sub_slots.append((eos, {}, total_iters))
        return True

    def new_signage_point(
        self,
        index: uint8,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        peak: Optional[SubBlockRecord],
        next_sub_slot_iters: uint64,
        signage_point: SignagePoint,
    ) -> bool:
        """
        Returns true if sp successfully added
        """

        if peak is None or peak.height < 2:
            sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
        else:
            sub_slot_iters = peak.sub_slot_iters

        # If we don't have this slot, return False
        assert 0 < index < self.constants.NUM_SPS_SUB_SLOT
        for sub_slot, sp_dict, start_ss_total_iters in self.finished_sub_slots:
            if sub_slot is None and start_ss_total_iters == 0:
                ss_challenge_hash = self.constants.FIRST_CC_CHALLENGE
                ss_reward_hash = self.constants.FIRST_RC_CHALLENGE
            else:
                ss_challenge_hash = sub_slot.challenge_chain.get_hash()
                ss_reward_hash = sub_slot.reward_chain.get_hash()
            if ss_challenge_hash == signage_point.cc_vdf.challenge:
                # If we do have this slot, find the Prev sub-block from SP and validate SP
                if peak is not None and start_ss_total_iters > peak.total_iters:
                    # We are in a future sub slot from the peak, so maybe there is a new SSI
                    checkpoint_size: uint64 = uint64(next_sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
                    delta_iters = checkpoint_size * index
                else:
                    # We are not in a future sub slot from the peak, so there is no new SSI
                    checkpoint_size: uint64 = uint64(sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
                    delta_iters = checkpoint_size * index
                sp_total_iters = start_ss_total_iters + delta_iters

                curr = peak
                if peak is None:
                    check_from_start_of_ss = True
                else:
                    check_from_start_of_ss = False
                    while curr.total_iters > start_ss_total_iters and curr.total_iters > sp_total_iters:
                        if curr.first_in_sub_slot:
                            # Did not find a sub-block where it's iters are before our sp_total_iters, in this ss
                            check_from_start_of_ss = True
                            break
                        curr = sub_blocks[curr.prev_hash]

                if check_from_start_of_ss:
                    # Check VDFs from start of sub slot
                    cc_vdf_info_expected = VDFInfo(
                        ss_challenge_hash,
                        ClassgroupElement.get_default_element(),
                        delta_iters,
                        signage_point.cc_vdf.output,
                    )

                    rc_vdf_info_expected = VDFInfo(
                        ss_reward_hash,
                        ClassgroupElement.get_default_element(),
                        delta_iters,
                        signage_point.rc_vdf.output,
                    )
                else:
                    # Check VDFs from curr
                    assert curr is not None
                    cc_vdf_info_expected = VDFInfo(
                        ss_challenge_hash,
                        curr.challenge_vdf_output,
                        uint64(sp_total_iters - curr.total_iters),
                        signage_point.cc_vdf.output,
                    )
                    rc_vdf_info_expected = VDFInfo(
                        curr.reward_infusion_new_challenge,
                        ClassgroupElement.get_default_element(),
                        uint64(sp_total_iters - curr.total_iters),
                        signage_point.rc_vdf.output,
                    )
                if not signage_point.cc_proof.is_valid(self.constants, signage_point.cc_vdf, cc_vdf_info_expected):
                    return False
                if not signage_point.rc_proof.is_valid(self.constants, signage_point.rc_vdf, rc_vdf_info_expected):
                    return False

                if index not in sp_dict:
                    sp_dict[index] = [signage_point]
                else:
                    sp_dict[index].append(signage_point)
                return True
        return False

    def get_signage_point(self, cc_signage_point: bytes32) -> Optional[SignagePoint]:
        if cc_signage_point == self.constants.FIRST_CC_CHALLENGE:
            return SignagePoint(None, None, None, None)

        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None and sub_slot.challenge_chain.get_hash() == cc_signage_point:
                return SignagePoint(None, None, None, None)
            for _, sps_at_index in sps.items():
                for sp in sps_at_index:
                    if sp.cc_vdf.output.get_hash() == cc_signage_point:
                        return sp
        return None

    def get_signage_point_by_index(
        self, challenge_hash: bytes32, index: uint8, last_rc_infusion: bytes32
    ) -> Optional[SignagePoint]:
        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None:
                cc_hash = sub_slot.challenge_chain.get_hash()
            else:
                cc_hash = self.constants.FIRST_CC_CHALLENGE

            if cc_hash == challenge_hash:
                if index == 0:
                    return SignagePoint(None, None, None, None)
                if index not in sps:
                    return None
                for sp in sps[index]:
                    if sp.rc_vdf.challenge == last_rc_infusion:
                        return sp
                return None
        return None

    def new_peak(
        self,
        peak: SubBlockRecord,
        peak_sub_slot: Optional[EndOfSubSlotBundle],  # None if in first slot
        prev_sub_slot: Optional[EndOfSubSlotBundle],  # None if not overflow, or in first/second slot
        reorg: bool,
        sub_blocks: Dict[bytes32, SubBlockRecord],
    ) -> Optional[EndOfSubSlotBundle]:
        """
        If the peak is an overflow block, must provide two sub-slots: one for the current sub-slot and one for
        the prev sub-slot (since we still might get more sub-blocks with an sp in the previous sub-slot)
        """
        new_finished_sub_slots = []
        total_iters = peak.infusion_sub_slot_total_iters(self.constants)
        if not reorg:
            # This is a new peak that adds to the last peak. We can clear data in old sub-slots. (and new ones)
            for index, (sub_slot, sps, total_iters) in enumerate(self.finished_sub_slots):
                if peak.overflow and prev_sub_slot is not None:
                    if sub_slot == prev_sub_slot:
                        # In the case of a peak overflow sub-block, the previous sub-slot is added
                        new_finished_sub_slots.append((sub_slot, sps, total_iters))
                        continue

                if sub_slot == peak_sub_slot:
                    new_finished_sub_slots.append([(sub_slot, sps, total_iters)])
                    self.finished_sub_slots = new_finished_sub_slots
        if reorg or len(new_finished_sub_slots) == 0:
            # This is either a reorg, which means some sub-blocks are reverted, or this sub slot is not in our current
            # cache, delete the entire cache and add this sub slot.
            self.clear_slots()
            if peak.overflow and prev_sub_slot is not None:
                prev_sub_slot_total_iters = peak.pos_sub_slot_total_iters(self.constants)
                self.finished_sub_slots = [(prev_sub_slot, {}, prev_sub_slot_total_iters)]
            self.finished_sub_slots.append((peak_sub_slot, {}, total_iters))

        for eos in self.future_eos_cache.get(peak.reward_infusion_new_challenge, []):
            if self.new_finished_sub_slot(eos, sub_blocks, peak):
                return eos  # Return new sub slot, if added
        # TODO: handle other caches
        return None

    def get_finished_sub_slots(
        self,
        prev_sb: Optional[SubBlockRecord],
        sub_block_records: Dict[bytes32, SubBlockRecord],
        pos_ss_challenge_hash: bytes32,
        extra_sub_slot: bool = False,
    ) -> List[EndOfSubSlotBundle]:
        """
        Returns all sub slots that have been completed between the prev sb and the new block we will create,
        which is denoted from the pos_challenge hash, and extra_sub_slot.
        NOTE: In the case of the overflow, passing in extra_sub_slot=True will add the necessary sub-slot. This might
        not be available until later though.
        """
        if prev_sb is not None:
            curr: SubBlockRecord = prev_sb
            while not curr.first_in_sub_slot:
                curr = sub_block_records[curr.prev_hash]
            final_sub_slot_in_chain: bytes32 = curr.finished_challenge_slot_hashes[-1]
        else:
            final_sub_slot_in_chain: bytes32 = self.constants.FIRST_CC_CHALLENGE

        pos_index: Optional[int] = None
        final_index: Optional[int] = None
        if prev_sb is None:
            if len(self.finished_sub_slots) < 1:
                raise ValueError("Should have finished sub slots")
            if self.finished_sub_slots[0][0] is not None:
                raise ValueError("First sub slot should be None")
            final_index = 0
            for index, (sub_slot, sps, total_iters) in enumerate(self.finished_sub_slots):
                if sub_slot is not None and sub_slot.challenge_chain.get_hash() == pos_ss_challenge_hash:
                    pos_index = index
        else:
            for index, (sub_slot, sps, total_iters) in enumerate(self.finished_sub_slots):
                if sub_slot is None:
                    pass
                if sub_slot.challenge_chain.get_hash() == pos_ss_challenge_hash:
                    pos_index = index
                if sub_slot.challenge_chain.get_hash() == final_sub_slot_in_chain:
                    final_index = index

        if pos_index is None or final_index is None:
            raise ValueError(f"Did not find challenge hash or peak pi: {pos_index} fi: {final_index}")

        if extra_sub_slot:
            new_final_index = pos_index + 1
        else:
            new_final_index = pos_index

        return [sub_slot for sub_slot, _, _, _ in self.finished_sub_slots[final_index + 1 : new_final_index + 1]]
