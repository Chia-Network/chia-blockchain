import logging
from typing import Dict, List, Optional, Tuple

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_ip_iters, calculate_sub_slot_iters
from src.full_node.sub_block_record import SubBlockRecord
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.types.unfinished_block import UnfinishedBlock
from src.types.vdf import VDFProof, VDFInfo
from src.util.ints import uint32, uint8, uint64, uint128

log = logging.getLogger(__name__)

SPs = List[Optional[Tuple[VDFInfo, VDFProof]]]


class FullNodeStore:
    constants: ConsensusConstants
    # Blocks which we have created, but don't have plot signatures yet
    candidate_blocks: Dict[bytes32, UnfinishedBlock]
    # Header hashes of unfinished blocks that we have seen recently
    seen_unfinished_blocks: set
    # Blocks which we have received but our blockchain does not reach, old ones are cleared
    disconnected_blocks: Dict[bytes32, FullBlock]
    # Unfinished blocks, keyed from reward hash
    unfinished_blocks: Dict[bytes32, UnfinishedBlock]

    # Finished slots and sps from the peak's slot onwards
    # We store all 32 SPs for each slot, starting as 32 Nones and filling them as we go
    # Also stores the total iters at the end of slot
    finished_sub_slots: List[Tuple[EndOfSubSlotBundle, SPs, SPs, uint128]]

    @classmethod
    async def create(cls, constants: ConsensusConstants):
        self = cls()
        # TODO(mariano): replace
        # self.proof_of_time_heights = {}

        self.constants = constants
        self.clear_slots()
        self.unfinished_blocks = {}
        self.candidate_blocks = {}
        self.seen_unfinished_blocks = set()
        self.disconnected_blocks = {}
        return self

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

    def add_unfinished_block(self, unfinished_block: UnfinishedBlock) -> None:
        self.unfinished_blocks[unfinished_block.reward_chain_sub_block.get_hash()] = unfinished_block

    def get_unfinished_block(self, unfinished_reward_hash: bytes32) -> Optional[UnfinishedBlock]:
        return self.unfinished_blocks.get(unfinished_reward_hash, None)

    def seen_unfinished_block(self, temp_header_hash: bytes32) -> bool:
        if temp_header_hash in self.seen_unfinished_blocks:
            return True
        self.seen_unfinished_blocks.add(temp_header_hash)
        return False

    def clear_seen_unfinished_blocks(self) -> None:
        self.seen_unfinished_blocks.clear()

    def get_unfinished_blocks(self) -> Dict[bytes32, UnfinishedBlock]:
        return self.unfinished_blocks

    def clear_unfinished_blocks_below(self, height: uint32) -> None:
        for partial_reward_hash, unfinished_block in self.unfinished_blocks.items():
            if unfinished_block.height < height:
                del self.unfinished_blocks[partial_reward_hash]

    def remove_unfinished_block(self, partial_reward_hash: bytes32):
        if partial_reward_hash in self.unfinished_blocks:
            del self.unfinished_blocks[partial_reward_hash]

    def clear_slots(self):
        self.finished_sub_slots.clear()

    def have_sub_slot(self, challenge_hash: bytes32, index: uint8) -> bool:
        for sub_slot, sps_cc, sps_rc, _ in self.finished_sub_slots:
            if sub_slot.challenge_chain_hash == challenge_hash:
                if index == 0:
                    return True
                return sps_cc[index] is not None and sps_rc[index] is not None
        return False

    def get_sub_slot(self, challenge_hash: bytes32) -> Optional[Tuple[EndOfSubSlotBundle, int, uint128]]:
        for index, (sub_slot, _, _, total_iters) in enumerate(self.finished_sub_slots):
            if sub_slot.challenge_chain.get_hash() == challenge_hash:
                return sub_slot, index, total_iters
        return None

    def new_finished_sub_slot(self, eos: EndOfSubSlotBundle, total_iters: uint128):
        """
        Returns true if finished slot successfully added
        """
        # First one is the challenge itself and will stay as None
        sps_cc = [None] * self.constants.NUM_CHECKPOINTS_PER_SLOT
        sps_rc = [None] * self.constants.NUM_CHECKPOINTS_PER_SLOT
        if len(self.finished_sub_slots) == 0:
            self.finished_sub_slots.append((eos, sps_cc, sps_rc, total_iters))
            return True
        if (
            eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge_hash
            != self.finished_sub_slots[-1][0].challenge_chain.get_hash()
        ):
            # This slot does not append to our next slot
            # This prevent other peers from appending fake VDFs to our cache
            return False
        self.finished_sub_slots.append((eos, sps_cc, sps_rc, total_iters))
        return True

    def get_signage_point(self, challenge_hash: bytes32, signage_point: bytes32):
        pass

    def new_signage_point(
        self,
        challenge_hash: bytes32,
        index: uint8,
        vdf_info_cc: VDFInfo,
        proof_cc: VDFProof,
        vdf_info_rc: VDFInfo,
        proof_rc: VDFProof,
    ) -> bool:
        """
        Returns true if sp successfully added
        """
        assert 0 < index < self.constants.NUM_CHECKPOINTS_PER_SLOT
        for sub_slot, sps_cc, sps_rc, _ in self.finished_sub_slots:
            if sub_slot.challenge_chain.get_hash() == challenge_hash:
                sps_cc[index] = (vdf_info_cc, proof_cc)
                sps_rc[index] = (vdf_info_rc, proof_rc)
                return True
        return False

    def remove_sub_slot(self, old_challenge_hash: bytes32):
        new_sub_slots = []
        for index, (sub_slot, sps_cc, sps_rc, total_iters) in enumerate(self.finished_sub_slots):
            if sub_slot.challenge_chain.get_hash() != old_challenge_hash:
                new_sub_slots.append((sub_slot, sps_cc, sps_rc, total_iters))
            else:
                # Force removal from the front, to ensure we are always clearing the cache
                assert index == 0
        self.finished_sub_slots = new_sub_slots

    def new_peak(
        self,
        peak: SubBlockRecord,
        peak_sub_slot: EndOfSubSlotBundle,
        total_iters: uint128,
        prev_sub_slot: Optional[EndOfSubSlotBundle],
        prev_sub_slot_total_iters: Optional[uint128],
        reorg: bool,
    ):
        """
        If the peak is an overflow block, must provide two sub-slots: one for the current sub-slot and one for
        the prev sub-slot (since we still might get more sub-blocks with an sp in the previous sub-slot)
        """
        if not reorg:
            # This is a new peak that adds to the last peak. We should clear any data that comes after the infusion
            # of this peak. We can also clear data in old sub-slots.
            sub_slot_iters: uint64 = calculate_sub_slot_iters(self.constants, peak.ips)
            checkpoint_size: uint64 = uint64(sub_slot_iters // self.constants.NUM_CHECKPOINTS_PER_SLOT)
            ip_iters = calculate_ip_iters(self.constants, peak.ips, peak.required_iters)
            sps_to_keep = ip_iters // checkpoint_size + 1
            new_finished_sub_slots = []
            for index, (sub_slot, sps_cc, sps_rc, total_iters) in enumerate(self.finished_sub_slots):
                if (prev_sub_slot is not None) and sub_slot == prev_sub_slot:
                    # In the case of a peak overflow sub-block, the previous sub-slot is added
                    new_finished_sub_slots.append((sub_slot, sps_cc, sps_rc, total_iters))

                if sub_slot == peak_sub_slot:
                    # Only saves signage points up to the peak, since the infusion changes future points
                    new_sps_cc = sps_cc[:sps_to_keep] + [None] * (self.constants.NUM_CHECKPOINTS_PER_SLOT - sps_to_keep)
                    new_sps_rc = sps_rc[:sps_to_keep] + [None] * (self.constants.NUM_CHECKPOINTS_PER_SLOT - sps_to_keep)
                    new_finished_sub_slots.append([(sub_slot, new_sps_cc, new_sps_rc, total_iters)])
                    self.finished_sub_slots = new_finished_sub_slots

        # This is either a reorg, which means some sub-blocks are reverted, or this sub slot is not in our current cache
        # delete the entire cache and add this sub slot.
        self.clear_slots()
        if prev_sub_slot is not None:
            assert prev_sub_slot_total_iters is not None
            self.new_finished_sub_slot(prev_sub_slot, prev_sub_slot_total_iters)
        self.new_finished_sub_slot(peak_sub_slot, total_iters)

    def get_finished_sub_slots(
        self,
        peak: SubBlockRecord,
        sub_block_records: Dict[bytes32, SubBlockRecord],
        pos_challenge_hash: bytes32,
        is_overflow: bool,
    ) -> List[EndOfSubSlotBundle]:
        """
        Returns all sub slots that have been completed between the current peak and the new block we will create,
        which is denoted from the pos_challenge hash, and is_overflow. In the case of the overflow, we have to add the
        new slot as well.
        """
        curr: SubBlockRecord = peak
        while not curr.first_in_sub_slot:
            curr = sub_block_records[curr.prev_hash]
        final_sub_slot_in_chain: bytes32 = curr.finished_challenge_slot_hashes[-1]
        pos_index: Optional[int] = None
        final_index: Optional[int] = None
        for index, (sub_slot, sps_cc, sps_rc, total_iters) in enumerate(self.finished_sub_slots):
            if sub_slot.challenge_chain.get_hash() == pos_challenge_hash:
                pos_index = index
            if sub_slot.challenge_chain.get_hash() == final_sub_slot_in_chain:
                final_index = index

        if pos_index is None or final_index is None:
            raise ValueError(f"Did not find challenge hash or peak pi: {pos_index} fi: {final_index}")

        if is_overflow:
            new_final_index = pos_index + 1
        else:
            new_final_index = pos_index
        return [sub_slot for sub_slot, _, _, _ in self.finished_sub_slots[final_index + 1 : new_final_index + 1]]
