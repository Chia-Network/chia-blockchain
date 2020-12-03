import logging
import random
from typing import Dict, Optional, List

from blspy import AugSchemeMPL

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    is_overflow_sub_block,
    calculate_iterations_quality,
    calculate_ip_iters,
)
from src.consensus.sub_block_record import SubBlockRecord
from src.types.classgroup import ClassgroupElement
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFProof, VDFInfo
from src.types.weight_proof import (
    WeightProof,
    SubEpochData,
    SubEpochChallengeSegment,
    SubSlotData,
    ProofBlockHeader,
)
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint8, uint128
from src.util.vdf_prover import get_vdf_info_and_proof


class WeightProofFactory:
    def __init__(
        self,
        constants: ConsensusConstants,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        header_cache: Dict[bytes32, HeaderBlock],
        height_to_hash: Dict[uint32, bytes32],
        name: str = None,
    ):
        self.constants = constants
        self.sub_blocks = sub_blocks
        self.header_cache = header_cache
        self.height_to_hash = height_to_hash
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

    def make_weight_proof(self, recent_blocks_n: uint32, total_number_of_blocks: uint32, tip: bytes32) -> WeightProof:
        """
        Creates a weight proof object
        """

        # todo assert recent blocks number
        # todo clean some of the logs after tests pass
        sub_epoch_data: List[SubEpochData] = []
        sub_epoch_segments: List[SubEpochChallengeSegment] = []
        proof_blocks: List[ProofBlockHeader] = []
        rng: random.Random = random.Random(tip)
        # ses_hash from the latest sub epoch summary before this part of the chain
        self.log.info(
            f"build weight proofs, peak : {self.sub_blocks[tip].height} num of blocks: {total_number_of_blocks}"
        )
        assert self.sub_blocks[tip].height >= total_number_of_blocks
        sub_epoch_n: uint32 = uint32(0)

        blocks_left = total_number_of_blocks
        curr_height = self.sub_blocks[tip].height - total_number_of_blocks
        total_overflow_blocks = 0
        while blocks_left != 0:
            # next sub block
            block = self.height_to_hash[curr_height]
            sub_block = self.sub_blocks[block]
            header_block = self.header_cache[block]
            if is_overflow_sub_block(self.constants, header_block.reward_chain_sub_block.signage_point_index):
                total_overflow_blocks += 1
                self.log.info(f"overflow block at height {curr_height}  ")
            # for each sub-epoch
            if sub_block.sub_epoch_summary_included is not None:
                self.log.info(
                    f"sub epoch end in block height {sub_block.height}  {sub_block.sub_epoch_summary_included}"
                )
                # we are going backwards, prepend sub_epoch_data
                sub_epoch_data.append(make_sub_epoch_data(sub_block.sub_epoch_summary_included))
                # get sub_epoch_blocks_n in sub_epoch
                sub_epoch_blocks_n = get_sub_epoch_block_num(sub_block, self.sub_blocks)
                self.log.info(f"sub epoch {sub_epoch_n} has {sub_epoch_blocks_n} blocks")
                #   sample sub epoch
                if choose_sub_epoch(sub_epoch_blocks_n, rng, total_number_of_blocks):
                    self.log.info(f"sub epoch {sub_epoch_n} chosen")
                    sub_epoch_segments.extend(
                        self.__create_sub_epoch_segments(
                            sub_block,
                            sub_epoch_blocks_n,
                            sub_epoch_n,
                        )
                    )

            if recent_blocks_n > 0:
                # add to needed reward chain recent blocks
                proof_blocks.append(
                    ProofBlockHeader(header_block.finished_sub_slots, header_block.reward_chain_sub_block)
                )
                recent_blocks_n -= 1

            blocks_left -= 1
            curr_height += 1
        self.log.info(f"total overflow blocks in proof {total_overflow_blocks}")
        return WeightProof(sub_epoch_data, sub_epoch_segments, proof_blocks)

    def validate_weight_proof(self, weight_proof: WeightProof, fork_point: SubBlockRecord) -> bool:
        self.log.info(f"fork point {fork_point.height}")
        # sub epoch summaries validate hashes
        self.log.info(f"validate summaries")
        summaries = self.validate_sub_epoch_summaries(weight_proof, fork_point)
        if summaries is None:
            return False
        self.log.info(f"validate sub epoch challenge segments")
        if not self._validate_segments(fork_point, summaries, weight_proof):
            return False
        # validate recent reward chain

        return True

    def validate_sub_epoch_summaries(self, weight_proof: WeightProof, fork_point: SubBlockRecord):
        fork_point_difficulty = uint64(fork_point.weight - self.sub_blocks[fork_point.prev_hash].weight)
        curr = fork_point
        while not curr.sub_epoch_summary_included:
            curr = self.sub_blocks[curr.prev_hash]
        self.log.info(f"prev sub_epoch summary at {curr.height}")
        prev_ses_hash = curr.sub_epoch_summary_included.get_hash()
        summaries, sub_epoch_data_weight = map_summaries(
            self.constants.SUB_EPOCH_SUB_BLOCKS, prev_ses_hash, weight_proof.sub_epochs, fork_point_difficulty
        )
        last_ses = summaries[uint32(len(summaries) - 1)]
        last_ses_block = get_last_ses_block_idx(self.constants, weight_proof.recent_chain_data)
        if last_ses_block is None:
            self.log.error(f"could not find first block after last sub epoch end")
            return None
        # validate weight
        # validate last ses_hash
        if last_ses.get_hash() != last_ses_block.finished_sub_slots[-1].challenge_chain.subepoch_summary_hash:
            self.log.error(
                f"failed to validate ses hashes block height {last_ses_block.height} {last_ses.get_hash()} "
                f" {last_ses_block.finished_sub_slots[-1].challenge_chain.subepoch_summary_has}"
            )
            return None
        return summaries

    def _validate_segments(self, fork_point: SubBlockRecord, summaries: Dict[uint32, SubEpochSummary], weight_proof):
        curr_ssi = fork_point.sub_slot_iters
        total_challenge_blocks, total_ip_iters = uint64(0), uint64(0)
        total_slot_iters, total_slots = uint64(0), uint64(0)
        # validate sub epoch samples
        for idx, segment in enumerate(weight_proof.sub_epoch_segments):
            self.log.info(f"validate {idx} segment")
            ses = summaries[segment.sub_epoch_n]
            if ses.new_sub_slot_iters is not None:
                curr_ssi: uint64 = ses.new_sub_slot_iters
            total_slot_iters += curr_ssi
            q_str = self._get_quality_string(segment, summaries[segment.sub_epoch_n], curr_ssi)
            if q_str is None:
                self.log.info(f"failed to validate {idx} segment space proof")
                return False

            # validate vdfs
            challenge = ses.prev_subepoch_summary_hash
            for sub_slot in segment.sub_slots:
                total_slots += 1
                vdf_info, _ = get_vdf_info_and_proof(
                    self.constants, ClassgroupElement.get_default_element(), challenge, curr_ssi
                )
                if not validate_sub_slot_vdfs(self.constants, sub_slot, vdf_info, sub_slot.is_challenge()):
                    self.log.info(f"failed to validate {idx} sub slot vdfs")
                    return False

                if sub_slot.is_challenge():
                    required_iters: uint64 = calculate_iterations_quality(
                        q_str,
                        sub_slot.proof_of_space.size,
                        challenge,
                        sub_slot.cc_signage_point_vdf.get_hash(),
                    )
                    total_ip_iters = +calculate_ip_iters(
                        self.constants, ses.new_ips, sub_slot.cc_signage_point_index, required_iters
                    )
                    total_challenge_blocks += 1
                    challenge = sub_slot.cc_slot_vdf.get_hash()
                else:
                    challenge = sub_slot.cc_infusion_to_slot_end_vdf.get_hash()

                    # validate reward chain sub slot obj with next ses
                    rc_sub_slot = RewardChainSubSlot(
                        segment.last_reward_chain_vdf_info,
                        segment.sub_slots[-1].cc_infusion_to_slot_end_vdf.get_hash(),
                        segment.sub_slots[-1].icc_infusion_to_slot_end_vdf.get_hash(),
                        uint8(0),
                    )

                    if not summaries[segment.sub_epoch_n + 1].reward_chain_hash == rc_sub_slot.get_hash():
                        self.log.error(f"segment {segment.sub_epoch_n} failed reward_chain_hash validation")
                        return False

            # todo floats
            avg_ip_iters = total_ip_iters / total_challenge_blocks
            avg_slot_iters = total_slot_iters / total_slots
            if avg_slot_iters / avg_ip_iters < float(self.constants.WEIGHT_PROOF_THRESHOLD):
                self.log.error(f"bad avg challenge block positioning ration: {avg_slot_iters / avg_ip_iters}")
                return False

    def __create_sub_epoch_segments(
        self, block: SubBlockRecord, sub_epoch_blocks_n: uint32, sub_epoch_n: uint32
    ) -> List[SubEpochChallengeSegment]:
        """
        receives the last block in sub epoch and creates List[SubEpochChallengeSegment] for that sub_epoch
        """

        segments: List[SubEpochChallengeSegment] = []
        curr = block

        count = sub_epoch_blocks_n
        while not count == 0:
            curr = self.sub_blocks[curr.prev_hash]
            count -= 1
            # not challenge block skip
            if not curr.is_challenge_sub_block(self.constants):
                continue

            self.log.info(f"sub epoch {sub_epoch_n} challenge segment, starts at {curr.height} ")
            challenge_sub_block = self.header_cache[curr.header_hash]
            segments.append(self._handle_challenge_segment(challenge_sub_block, sub_epoch_n))

        return segments

    def _handle_challenge_segment(self, block: HeaderBlock, sub_epoch_n: uint32) -> SubEpochChallengeSegment:
        sub_slots: List[SubSlotData] = []
        self.log.info(f"create challenge segment for block {block.header_hash} height {block.height} ")

        # VDFs from sub slots before challenge block
        self.log.info(f"create ip vdf for block {block.header_hash} height {block.height} ")
        first_sub_slots, end_height = self._first_sub_slots_data(block)
        sub_slots.extend(first_sub_slots)

        # VDFs from slot after challenge block to end of slot
        self.log.info(f"create slot end vdf for block {block.header_hash} height {block.height} ")

        challenge_slot_end_sub_slots = self._get_slot_end_vdf(self.header_cache[self.height_to_hash[end_height]])

        sub_slots.extend(challenge_slot_end_sub_slots)
        self.log.info(f"segment number of sub slots {len(sub_slots)}")
        return SubEpochChallengeSegment(sub_epoch_n, block.reward_chain_sub_block.reward_chain_ip_vdf, sub_slots)

    def _get_slot_end_vdf(self, block: HeaderBlock) -> List[SubSlotData]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        curr = block
        cc_proofs: List[VDFProof] = []
        icc_proofs: List[VDFProof] = []
        sub_slots_data: List[SubSlotData] = []
        while curr.height + 1 < len(self.sub_blocks):
            curr = self.header_cache[self.height_to_hash[curr.height + 1]]
            if len(curr.finished_sub_slots) > 0:
                # slot finished combine proofs and add slot data to list
                sub_slots_data.append(
                    SubSlotData(
                        None, None, None, None, combine_proofs(cc_proofs), combine_proofs(icc_proofs), None, None, None
                    )
                )

                # handle finished empty sub slots
                for sub_slot in curr.finished_sub_slots:
                    sub_slots_data.append(empty_sub_slot_data(sub_slot.proofs))
                    if sub_slot.reward_chain.deficit == self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        # end of challenge slot
                        break

                # new sub slot
                cc_proofs = []

            # append sub slot proofs
            icc_proofs.append(curr.infused_challenge_chain_ip_proof)
            cc_proofs.extend([curr.challenge_chain_sp_proof, curr.challenge_chain_ip_proof])

        return sub_slots_data

    # returns a challenge chain vdf from slot start to signage point
    def _first_sub_slots_data(self, block: HeaderBlock) -> (List[SubSlotData], uint64):
        # combine cc vdfs of all reward blocks from the start of the sub slot to end
        sub_slots: List[SubSlotData] = []
        # challenge block Proof of space
        proof_of_space = block.reward_chain_sub_block.proof_of_space
        # challenge block Signature of signage point
        cc_signage_point_sig = block.reward_chain_sub_block.challenge_chain_sp_signature

        # todo vdf of the overflow blocks before the challenge block ?

        sub_slots: List[SubSlotData]
        # get all finished sub slots
        if len(block.finished_sub_slots) > 0:
            for sub_slot in block.finished_sub_slots:
                sub_slots.append(empty_sub_slot_data(sub_slot.proofs))

        # find sub slot end
        curr = block
        cc_slot_end_vdf: List[VDFProof] = []
        icc_slot_end_vdf: List[VDFProof] = []
        while True:
            curr = self.header_cache[self.height_to_hash[curr.height + 1]]
            if len(curr.finished_sub_slots) > 0:
                # sub slot ended
                next_slot_height = curr.height + 1
                break

            cc_slot_end_vdf.extend([curr.challenge_chain_sp_proof, curr.challenge_chain_ip_proof])
            icc_slot_end_vdf.append(curr.infused_challenge_chain_ip_proof)

        if block.reward_chain_sub_block.challenge_chain_sp_vdf is None:
            if len(block.finished_sub_slots) > 0:
                self.log.info(
                    f" cc vdf  {block.finished_sub_slots[-1].challenge_chain.challenge_chain_end_of_slot_vdf}"
                )
                self.log.info(f"cc end of slot {block.finished_sub_slots[-1].challenge_chain}")

        sub_slots.append(
            SubSlotData(
                proof_of_space,
                cc_signage_point_sig,
                block.challenge_chain_sp_proof,
                block.challenge_chain_ip_proof,
                combine_proofs(cc_slot_end_vdf),
                combine_proofs(icc_slot_end_vdf),
                block.reward_chain_sub_block.signage_point_index,
                None,
                None,
            )
        )

        return sub_slots, next_slot_height

    def _get_quality_string(
        self, segment: SubEpochChallengeSegment, ses: SubEpochSummary, slot_iters: uint64
    ) -> Optional[bytes32]:

        # find challenge block sub slot
        challenge_sub_slot: Optional[SubSlotData] = None
        idx = 0
        for idx, slot in enumerate(segment.sub_slots):
            if slot.proof_of_space is not None:
                challenge_sub_slot = slot
                break

        cc_vdf, _ = get_vdf_info_and_proof(
            self.constants, ClassgroupElement.get_default_element(), std_hash(ses), slot_iters
        )
        # get challenge
        cc_sub_slot = ChallengeChainSubSlot(
            cc_vdf, None, ses.prev_subepoch_summary_hash, ses.new_sub_slot_iters, ses.new_difficulty
        )

        self.log.info(f"cc_vdf {cc_vdf}")
        self.log.info(f"cc_end_of_slot {cc_sub_slot}")

        # check filter
        if challenge_sub_slot.cc_signage_point_vdf is None:
            cc_sp_hash: bytes32 = cc_sub_slot.get_hash()
        else:
            cc_sp_hash = challenge_sub_slot.challenge_chain_sp_vdf.output.get_hash()

        if not AugSchemeMPL.verify(
            challenge_sub_slot.proof_of_space.plot_public_key,
            cc_sp_hash,
            challenge_sub_slot.cc_sp_sig,
        ):
            self.log.error(f"failed to validate filter {cc_sp_hash},{challenge_sub_slot.cc_sp_sig}")
            return None

        # validate proof of space
        return challenge_sub_slot.proof_of_space.verify_and_get_quality_string(
            self.constants,
            cc_sub_slot.get_hash(),
            challenge_sub_slot.cc_signage_point_vdf,
        )


def combine_proofs(proofs: List[VDFProof]) -> VDFProof:
    # todo

    return VDFProof(witness_type=uint8(0), witness=b"")


def make_sub_epoch_data(
    sub_epoch_summary: SubEpochSummary,
) -> SubEpochData:
    reward_chain_hash: bytes32 = sub_epoch_summary.reward_chain_hash
    #  Number of subblocks overflow in previous slot
    previous_sub_epoch_overflows: uint8 = sub_epoch_summary.num_sub_blocks_overflow  # total in sub epoch - expected
    #  New work difficulty and iterations per sub-slot
    sub_slot_iters: Optional[uint64] = sub_epoch_summary.new_sub_slot_iters
    new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty
    return SubEpochData(reward_chain_hash, previous_sub_epoch_overflows, sub_slot_iters, new_difficulty)


def get_sub_epoch_block_num(last_block: SubBlockRecord, sub_blocks: Dict[bytes32, SubBlockRecord]) -> uint32:
    """
    returns the number of blocks in a sub epoch ending with
    """
    # count from end of sub_epoch
    if last_block.sub_epoch_summary_included is None:
        raise Exception("block does not finish a sub_epoch")

    curr = sub_blocks[last_block.prev_hash]
    count: uint32 = uint32(0)
    while not curr.sub_epoch_summary_included:
        # todo skip overflows from last sub epoch
        if curr.height == 0:
            return count

        curr = sub_blocks[curr.prev_hash]
        count += 1
    count += 1

    return count


def choose_sub_epoch(sub_epoch_blocks_n: uint32, rng: random.Random, total_number_of_blocks: uint32) -> bool:
    prob = sub_epoch_blocks_n / total_number_of_blocks
    for i in range(sub_epoch_blocks_n):
        if rng.random() < prob:
            return True
    return False


# returns a challenge chain vdf from infusion point to end of slot


def count_sub_epochs_in_range(
    curr: SubBlockRecord, sub_blocks: Dict[bytes32, SubBlockRecord], total_number_of_blocks: int
):
    sub_epochs_n = 0
    while not total_number_of_blocks == 0:
        assert curr.height != 0
        curr = sub_blocks[curr.prev_hash]
        if curr.sub_epoch_summary_included is not None:
            sub_epochs_n += 1
        total_number_of_blocks -= 1
    return sub_epochs_n


# todo fix to correct vdf inputs
def validate_sub_slot_vdfs(
    constants: ConsensusConstants, sub_slot: SubSlotData, vdf_info: VDFInfo, infused: bool
) -> bool:
    default = ClassgroupElement.get_default_element()
    if infused:
        if not sub_slot.cc_signage_point_vdf.is_valid(constants, default, vdf_info):
            return False
        if not sub_slot.cc_infusion_point_vdf.is_valid(constants, default, vdf_info):
            return False
        if not sub_slot.cc_infusion_to_slot_end_vdf.is_valid(constants, default, vdf_info):
            return False
        if not sub_slot.icc_infusion_to_slot_end_vdf.is_valid(constants, default, vdf_info):
            return False

        return True

    return sub_slot.cc_slot_vdf.is_valid(constants, ClassgroupElement.get_default_element(), vdf_info)


def map_summaries(
    sub_blocks_for_se: uint32,
    ses_hash: bytes32,
    sub_epoch_data: List[SubEpochData],
    curr_difficulty: uint64,
) -> (Dict[uint32, SubEpochSummary], uint128):
    sub_epoch_data_weight: uint128 = uint128(0)
    summaries: Dict[uint32, SubEpochSummary] = {}

    for idx, data in enumerate(sub_epoch_data):
        ses = SubEpochSummary(
            ses_hash,
            data.reward_chain_hash,
            data.num_sub_blocks_overflow,
            data.new_difficulty,
            data.new_sub_slot_iters,
        )

        # if new epoch update diff and iters
        if data.new_sub_slot_iters is not None:
            curr_difficulty = data.new_difficulty

        sub_epoch_data_weight += curr_difficulty * (sub_blocks_for_se + data.num_sub_blocks_overflow)

        # add to dict
        summaries[idx] = ses
        ses_hash = std_hash(ses)
    return summaries, sub_epoch_data_weight


def get_last_ses_block_idx(
    constants: ConsensusConstants, recent_reward_chain: List[ProofBlockHeader]
) -> Optional[ProofBlockHeader]:
    for idx, block in enumerate(reversed(recent_reward_chain)):
        if uint8(block.reward_chain_sub_block.sub_block_height % constants.SUB_EPOCH_SUB_BLOCKS) == 0:
            idx = len(recent_reward_chain) - 1 - idx  # reverse
            # find first block after sub slot end
            curr = recent_reward_chain[idx]
            while len(curr.finished_sub_slots) == 0:
                idx += 1
                curr = recent_reward_chain[idx]
            return curr
    return None


def empty_sub_slot_data(proofs: SubSlotProofs):
    return SubSlotData(
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        proofs.challenge_chain_slot_proof,
        proofs.infused_challenge_chain_slot_proof,
    )
