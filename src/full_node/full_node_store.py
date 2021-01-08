import logging
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from src.consensus.constants import ConsensusConstants
from src.full_node.signage_point import SignagePoint
from src.consensus.sub_block_record import SubBlockRecord
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
    candidate_blocks: Dict[bytes32, Tuple[uint32, UnfinishedBlock]]

    # Header hashes of unfinished blocks that we have seen recently
    seen_unfinished_blocks: set

    # Blocks which we have received but our blockchain does not reach, old ones are cleared
    disconnected_blocks: Dict[bytes32, FullBlock]

    # Unfinished blocks, keyed from reward hash
    unfinished_blocks: Dict[bytes32, Tuple[uint32, UnfinishedBlock]]

    # Finished slots and sps from the peak's slot onwards
    # We store all 32 SPs for each slot, starting as 32 Nones and filling them as we go
    # Also stores the total iters at the end of slot
    # For the first sub-slot, EndOfSlotBundle is None
    finished_sub_slots: List[Tuple[Optional[EndOfSubSlotBundle], List[Optional[SignagePoint]], uint128]]

    # These caches maintain objects which depend on infused sub-blocks in the reward chain, that we
    # might receive before the sub-blocks themselves. The dict keys are the reward chain challenge hashes.

    # End of slots which depend on infusions that we don't have
    future_eos_cache: Dict[bytes32, List[EndOfSubSlotBundle]]

    # Signage points which depend on infusions that we don't have
    future_sp_cache: Dict[bytes32, List[SignagePoint]]

    # Infusion point VDFs which depend on infusions that we don't have
    future_ip_cache: Dict[bytes32, List[timelord_protocol.NewInfusionPointVDF]]

    def __init__(self):
        self.candidate_blocks = {}
        self.seen_unfinished_blocks = set()
        self.disconnected_blocks = {}
        self.unfinished_blocks = {}
        self.finished_sub_slots = []
        self.future_eos_cache = {}
        self.future_sp_cache = {}
        self.future_ip_cache = {}

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
        sub_height: uint32,
        unfinished_block: UnfinishedBlock,
    ):
        self.candidate_blocks[quality_string] = (sub_height, unfinished_block)

    def get_candidate_block(self, quality_string: bytes32) -> Optional[UnfinishedBlock]:
        result = self.candidate_blocks.get(quality_string, None)
        if result is None:
            return None
        return result[1]

    def clear_candidate_blocks_below(self, sub_height: uint32) -> None:
        del_keys = []
        for key, value in self.candidate_blocks.items():
            if value[0] < sub_height:
                del_keys.append(key)
        for key in del_keys:
            try:
                del self.candidate_blocks[key]
            except KeyError:
                pass

    def seen_unfinished_block(self, object_hash: bytes32) -> bool:
        if object_hash in self.seen_unfinished_blocks:
            return True
        self.seen_unfinished_blocks.add(object_hash)
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

    def clear_disconnected_blocks_below(self, sub_height: uint32) -> None:
        for key in list(self.disconnected_blocks.keys()):
            if self.disconnected_blocks[key].sub_block_height < sub_height:
                del self.disconnected_blocks[key]

    def add_unfinished_block(self, sub_height: uint32, unfinished_block: UnfinishedBlock) -> None:
        self.unfinished_blocks[unfinished_block.partial_hash] = (
            sub_height,
            unfinished_block,
        )

    def get_unfinished_block(self, unfinished_reward_hash: bytes32) -> Optional[UnfinishedBlock]:
        result = self.unfinished_blocks.get(unfinished_reward_hash, None)
        if result is None:
            return None
        return result[1]

    def get_unfinished_blocks(self) -> Dict[bytes32, Tuple[uint32, UnfinishedBlock]]:
        return self.unfinished_blocks

    def clear_unfinished_blocks_below(self, sub_height: uint32) -> None:
        del_keys: List[bytes32] = []
        for partial_reward_hash, (
            unf_height,
            unfinished_block,
        ) in self.unfinished_blocks.items():
            if unf_height < sub_height:
                del_keys.append(partial_reward_hash)
        for del_key in del_keys:
            del self.unfinished_blocks[del_key]

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
        assert len(self.finished_sub_slots) >= 1
        for index, (sub_slot, _, total_iters) in enumerate(self.finished_sub_slots):
            if sub_slot is not None and sub_slot.challenge_chain.get_hash() == challenge_hash:
                return sub_slot, index, total_iters
        return None

    def initialize_genesis_sub_slot(self):
        self.clear_slots()
        self.finished_sub_slots = [(None, [None] * self.constants.NUM_SPS_SUB_SLOT, uint128(0))]

    def new_finished_sub_slot(
        self,
        eos: EndOfSubSlotBundle,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        peak: Optional[SubBlockRecord],
    ) -> Optional[List[timelord_protocol.NewInfusionPointVDF]]:
        """
        Returns false if not added. Returns a list if added. The list contains all infusion points that depended
        on this sub slot
        TODO: do full validation here
        """
        assert len(self.finished_sub_slots) >= 1

        if len(self.finished_sub_slots) == 0:
            log.warning("no finished sub slots")
            return None

        last_slot, _, last_slot_iters = self.finished_sub_slots[-1]
        last_slot_ch = (
            last_slot.challenge_chain.get_hash() if last_slot is not None else self.constants.FIRST_CC_CHALLENGE
        )
        last_slot_rc_hash = (
            last_slot.reward_chain.get_hash() if last_slot is not None else self.constants.FIRST_RC_CHALLENGE
        )
        # Skip if already present
        for slot, _, _ in self.finished_sub_slots:
            if slot == eos:
                return []

        if eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge != last_slot_ch:
            # This slot does not append to our next slot
            # This prevent other peers from appending fake VDFs to our cache
            return None

        # TODO: Fix
        # if not eos.proofs.challenge_chain_slot_proof.is_valid(
        #     self.constants, ClassgroupElement.get_default_element(),
        #     replace(eos.challenge_chain.challenge_chain_end_of_slot_vdf,
        # ):
        #     return False
        # if not eos.proofs.reward_chain_slot_proof.is_valid(
        #     self.constants, ClassgroupElement.get_default_element(), eos.reward_chain.end_of_slot_vdf
        # ):
        #     return False
        # if eos.infused_challenge_chain is not None:
        #     # TODO: Fix
        #     if not eos.proofs.infused_challenge_chain_slot_proof.is_valid(
        #         self.constants,
        #         ClassgroupElement.get_default_element(),
        #         eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
        #     ):
        #         return False

        total_iters = uint128(
            last_slot_iters + eos.challenge_chain.challenge_chain_end_of_slot_vdf.number_of_iterations
        )

        if peak is not None and peak.total_iters > last_slot_iters:
            # Peak is in this slot
            rc_challenge = eos.reward_chain.end_of_slot_vdf.challenge
            if peak.reward_infusion_new_challenge != rc_challenge:
                # We don't have this challenge hash yet
                if rc_challenge not in self.future_eos_cache:
                    self.future_eos_cache[rc_challenge] = []
                self.future_eos_cache[rc_challenge].append(eos)
                log.warning(f"Don't have challenge hash {rc_challenge}")
                return None
            if peak.total_iters + eos.reward_chain.end_of_slot_vdf.number_of_iterations != total_iters:
                log.error(
                    f"Invalid iterations {peak.total_iters} {eos.reward_chain.end_of_slot_vdf.number_of_iterations} "
                    f"{total_iters}"
                )
                return None

            if peak.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                curr = peak
                while not curr.first_in_sub_slot and not curr.is_challenge_sub_block(self.constants):
                    curr = sub_blocks[curr.prev_hash]
                if curr.is_challenge_sub_block(self.constants):
                    icc_start_challenge_hash = curr.challenge_block_info_hash
                else:
                    assert curr.finished_infused_challenge_slot_hashes is not None
                    icc_start_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
                if peak.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    assert eos.infused_challenge_chain is not None
                    if (
                        eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge
                        != icc_start_challenge_hash
                    ):
                        return None
        else:
            # Empty slot after the peak
            if eos.reward_chain.end_of_slot_vdf.challenge != last_slot_rc_hash:
                return None

            if (
                last_slot is not None
                and last_slot.reward_chain.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
            ):
                assert eos.infused_challenge_chain is not None
                assert last_slot.infused_challenge_chain is not None
                # Have infused challenge chain that must be verified
                if (
                    eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge
                    != last_slot.infused_challenge_chain.get_hash()
                ):
                    return None

        self.finished_sub_slots.append((eos, [None] * self.constants.NUM_SPS_SUB_SLOT, total_iters))

        new_ips: List[timelord_protocol.NewInfusionPointVDF] = []
        for ip in self.future_ip_cache.get(eos.reward_chain.get_hash(), []):
            new_ips.append(ip)

        return new_ips

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
        assert len(self.finished_sub_slots) >= 1

        if peak is None or peak.sub_block_height < 2:
            sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
        else:
            sub_slot_iters = peak.sub_slot_iters

        # If we don't have this slot, return False
        if index == 0 or index >= self.constants.NUM_SPS_SUB_SLOT:
            return False
        assert (
            signage_point.cc_vdf is not None
            and signage_point.cc_proof is not None
            and signage_point.rc_vdf is not None
            and signage_point.rc_proof is not None
        )
        for sub_slot, sp_arr, start_ss_total_iters in self.finished_sub_slots:
            if sub_slot is None:
                assert start_ss_total_iters == 0
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
                    delta_iters: uint64 = uint64(checkpoint_size * index)
                    future_sub_slot: bool = True
                else:
                    # We are not in a future sub slot from the peak, so there is no new SSI
                    checkpoint_size = uint64(sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
                    delta_iters = uint64(checkpoint_size * index)
                    future_sub_slot = False
                sp_total_iters = start_ss_total_iters + delta_iters

                curr = peak
                if peak is None or future_sub_slot:
                    check_from_start_of_ss = True
                else:
                    check_from_start_of_ss = False
                    while (
                        curr is not None
                        and curr.total_iters > start_ss_total_iters
                        and curr.total_iters > sp_total_iters
                    ):
                        if curr.first_in_sub_slot:
                            # Did not find a sub-block where it's iters are before our sp_total_iters, in this ss
                            check_from_start_of_ss = True
                            break
                        curr = sub_blocks[curr.prev_hash]

                if check_from_start_of_ss:
                    # Check VDFs from start of sub slot
                    cc_vdf_info_expected = VDFInfo(
                        ss_challenge_hash,
                        delta_iters,
                        signage_point.cc_vdf.output,
                    )

                    rc_vdf_info_expected = VDFInfo(
                        ss_reward_hash,
                        delta_iters,
                        signage_point.rc_vdf.output,
                    )
                else:
                    # Check VDFs from curr
                    assert curr is not None
                    cc_vdf_info_expected = VDFInfo(
                        ss_challenge_hash,
                        uint64(sp_total_iters - curr.total_iters),
                        signage_point.cc_vdf.output,
                    )
                    rc_vdf_info_expected = VDFInfo(
                        curr.reward_infusion_new_challenge,
                        uint64(sp_total_iters - curr.total_iters),
                        signage_point.rc_vdf.output,
                    )
                if not signage_point.cc_vdf == replace(cc_vdf_info_expected, number_of_iterations=delta_iters):
                    return False
                if check_from_start_of_ss:
                    start_ele = ClassgroupElement.get_default_element()
                else:
                    assert curr is not None
                    start_ele = curr.challenge_vdf_output
                if not signage_point.cc_proof.is_valid(
                    self.constants,
                    start_ele,
                    cc_vdf_info_expected,
                ):
                    return False

                if rc_vdf_info_expected.challenge != signage_point.rc_vdf.challenge:
                    # This signage point is probably outdated
                    return False

                if not signage_point.rc_proof.is_valid(
                    self.constants,
                    ClassgroupElement.get_default_element(),
                    signage_point.rc_vdf,
                    rc_vdf_info_expected,
                ):
                    return False

                sp_arr[index] = signage_point
                return True
        return False

    def get_signage_point(self, cc_signage_point: bytes32) -> Optional[SignagePoint]:
        assert len(self.finished_sub_slots) >= 1
        if cc_signage_point == self.constants.FIRST_CC_CHALLENGE:
            return SignagePoint(None, None, None, None)

        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None and sub_slot.challenge_chain.get_hash() == cc_signage_point:
                return SignagePoint(None, None, None, None)
            for sp in sps:
                if sp is not None:
                    assert sp.cc_vdf is not None
                    if sp.cc_vdf.output.get_hash() == cc_signage_point:
                        return sp
        return None

    def get_signage_point_by_index(
        self, challenge_hash: bytes32, index: uint8, last_rc_infusion: bytes32
    ) -> Optional[SignagePoint]:
        assert len(self.finished_sub_slots) >= 1
        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None:
                cc_hash = sub_slot.challenge_chain.get_hash()
            else:
                cc_hash = self.constants.FIRST_CC_CHALLENGE

            if cc_hash == challenge_hash:
                if index == 0:
                    return SignagePoint(None, None, None, None)
                sp: Optional[SignagePoint] = sps[index]
                if sp is not None:
                    assert sp.rc_vdf is not None
                    if sp.rc_vdf.challenge == last_rc_infusion:
                        return sp
                return None
        return None

    def have_newer_signage_point(self, challenge_hash: bytes32, index: uint8, last_rc_infusion: bytes32) -> bool:
        """
        Returns true if we have a signage point at this index which is based on a newer infusion.
        """
        assert len(self.finished_sub_slots) >= 1
        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None:
                cc_hash = sub_slot.challenge_chain.get_hash()
            else:
                cc_hash = self.constants.FIRST_CC_CHALLENGE

            if cc_hash == challenge_hash:
                found_rc_hash = False
                for i in range(0, index):
                    sp: Optional[SignagePoint] = sps[i]
                    if sp is not None and sp.rc_vdf is not None and sp.rc_vdf.challenge == last_rc_infusion:
                        found_rc_hash = True
                sp = sps[index]
                if (
                    found_rc_hash
                    and sp is not None
                    and sp.rc_vdf is not None
                    and sp.rc_vdf.challenge != last_rc_infusion
                ):
                    return True
        return False

    def new_peak(
        self,
        peak: SubBlockRecord,
        sp_sub_slot: Optional[EndOfSubSlotBundle],  # None if not overflow, or in first/second slot
        ip_sub_slot: Optional[EndOfSubSlotBundle],  # None if in first slot
        reorg: bool,
        sub_blocks: Dict[bytes32, SubBlockRecord],
    ) -> Tuple[Optional[EndOfSubSlotBundle], List[SignagePoint], List[timelord_protocol.NewInfusionPointVDF]]:
        """
        If the peak is an overflow block, must provide two sub-slots: one for the current sub-slot and one for
        the prev sub-slot (since we still might get more sub-blocks with an sp in the previous sub-slot)
        """
        assert len(self.finished_sub_slots) >= 1
        new_finished_sub_slots = []
        total_iters_peak = peak.ip_sub_slot_total_iters(self.constants)
        ip_sub_slot_found = False
        if not reorg:
            # This is a new peak that adds to the last peak. We can clear data in old sub-slots. (and new ones)
            for index, (sub_slot, sps, total_iters) in enumerate(self.finished_sub_slots):
                if sub_slot == sp_sub_slot:
                    # In the case of a peak overflow sub-block (or first ss), the previous sub-slot is added
                    if sp_sub_slot is None:
                        # This is a non-overflow sub block
                        if (
                            ip_sub_slot is not None
                            and ip_sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
                            == self.constants.FIRST_CC_CHALLENGE
                        ):
                            new_finished_sub_slots.append((sub_slot, sps, total_iters))
                            continue

                    else:
                        # Overflow sub block
                        new_finished_sub_slots.append((sub_slot, sps, total_iters))
                        continue
                if sub_slot == ip_sub_slot:
                    ip_sub_slot_found = True
                    new_finished_sub_slots.append((sub_slot, sps, total_iters))
            self.finished_sub_slots = new_finished_sub_slots
        if reorg or not ip_sub_slot_found:
            # This is either a reorg, which means some sub-blocks are reverted, or this sub slot is not in our current
            # cache, delete the entire cache and add this sub slot.
            self.clear_slots()
            if peak.overflow:
                prev_sub_slot_total_iters = peak.sp_sub_slot_total_iters(self.constants)
                assert total_iters_peak != prev_sub_slot_total_iters
                self.finished_sub_slots = [
                    (
                        sp_sub_slot,
                        [None] * self.constants.NUM_SPS_SUB_SLOT,
                        prev_sub_slot_total_iters,
                    )
                ]
            log.info(f"5. Adding sub slot {ip_sub_slot is None}, total iters: {total_iters_peak}")
            self.finished_sub_slots.append(
                (
                    ip_sub_slot,
                    [None] * self.constants.NUM_SPS_SUB_SLOT,
                    total_iters_peak,
                )
            )

        new_eos: Optional[EndOfSubSlotBundle] = None
        new_sps: List[SignagePoint] = []
        new_ips: List[timelord_protocol.NewInfusionPointVDF] = []

        for eos in self.future_eos_cache.get(peak.reward_infusion_new_challenge, []):
            if self.new_finished_sub_slot(eos, sub_blocks, peak) is not None:
                new_eos = eos
                break

        # This cache is not currently being used
        for sp in self.future_sp_cache.get(peak.reward_infusion_new_challenge, []):
            assert sp.cc_vdf is not None
            index = uint8(sp.cc_vdf.number_of_iterations // peak.sub_slot_iters)
            if self.new_signage_point(index, sub_blocks, peak, peak.sub_slot_iters, sp):
                new_sps.append(sp)

        for ip in self.future_ip_cache.get(peak.reward_infusion_new_challenge, []):
            new_ips.append(ip)

        self.future_eos_cache.pop(peak.reward_infusion_new_challenge, [])
        self.future_sp_cache.pop(peak.reward_infusion_new_challenge, [])
        self.future_ip_cache.pop(peak.reward_infusion_new_challenge, [])

        return new_eos, new_sps, new_ips

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
        # TODO: review this code
        """
        assert len(self.finished_sub_slots) >= 1
        pos_index: Optional[int] = None
        final_index: int = -1

        if prev_sb is not None:
            curr: SubBlockRecord = prev_sb
            while not curr.first_in_sub_slot:
                curr = sub_block_records[curr.prev_hash]
            assert curr.finished_challenge_slot_hashes is not None
            final_sub_slot_in_chain: bytes32 = curr.finished_challenge_slot_hashes[-1]
        else:
            final_sub_slot_in_chain = self.constants.FIRST_CC_CHALLENGE
            final_index = 0

        if pos_ss_challenge_hash == self.constants.FIRST_CC_CHALLENGE:
            pos_index = 0
        if prev_sb is None:
            final_index = 0
            for index, (sub_slot, sps, total_iters) in enumerate(self.finished_sub_slots):
                if sub_slot is not None and sub_slot.challenge_chain.get_hash() == pos_ss_challenge_hash:
                    pos_index = index
        else:
            for index, (sub_slot, sps, total_iters) in enumerate(self.finished_sub_slots):
                if sub_slot is None:
                    continue
                if sub_slot.challenge_chain.get_hash() == pos_ss_challenge_hash:
                    pos_index = index
                if sub_slot.challenge_chain.get_hash() == final_sub_slot_in_chain:
                    final_index = index
                if sub_slot is None and final_sub_slot_in_chain == self.constants.FIRST_CC_CHALLENGE:
                    final_index = index

        if pos_index is None or final_index is None:
            raise ValueError(
                f"Did not find challenge hash or peak pi: {pos_index} fi: {final_index} {len(sub_block_records)}"
            )

        if extra_sub_slot:
            new_final_index = pos_index + 1
        else:
            new_final_index = pos_index
        if len(self.finished_sub_slots) < new_final_index + 1:
            raise ValueError("Don't have enough sub-slots")

        return [
            sub_slot
            for sub_slot, _, _, in self.finished_sub_slots[final_index + 1 : new_final_index + 1]
            if sub_slot is not None
        ]
