import logging
import random
from typing import Dict, Optional, List

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_ip_iters,
)
from src.consensus.sub_block_record import SubBlockRecord
from src.types.classgroup import ClassgroupElement
from src.types.header_block import HeaderBlock
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeChainSubSlot, RewardChainSubSlot
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFProof, VDFInfo
from src.types.weight_proof import (
    WeightProof,
    SubEpochData,
    SubEpochChallengeSegment,
    SubSlotData,
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

    def make_weight_proof(self, recent_blocks_n: uint32, total_number_of_blocks: uint32) -> WeightProof:
        """
        Creates a weight proof object
        """

        # todo assert recent blocks number
        tip = self.height_to_hash[uint32(len(self.height_to_hash) - 1)]
        sub_epoch_data: List[SubEpochData] = []
        sub_epoch_segments: List[SubEpochChallengeSegment] = []
        proof_blocks: List[RewardChainSubBlock] = []
        curr: SubBlockRecord = self.sub_blocks[tip]
        rng: random.Random = random.Random(tip)
        # ses_hash from the latest sub epoch summary before this part of the chain
        self.log.info(
            f"build weight proofs peak : {self.sub_blocks[tip].header_hash} num of blocks: {total_number_of_blocks}"
        )
        assert self.sub_blocks[tip].height > total_number_of_blocks
        sub_epoch_n = count_sub_epochs_in_range(curr, self.sub_blocks, total_number_of_blocks)
        sub_epoch_reverse_idx: uint32 = uint32(0)

        blocks_left = total_number_of_blocks
        while blocks_left > 0:
            # next sub block
            curr = self.sub_blocks[curr.prev_hash]
            header_block = self.header_cache[curr.header_hash]
            # for each sub-epoch
            if curr.sub_epoch_summary_included is not None:
                self.log.info(f"sub epoch end in block height {curr.height}")
                sub_epoch_data.append(make_sub_epoch_data(curr.sub_epoch_summary_included))
                # get sub_epoch_blocks_n in sub_epoch
                sub_epoch_blocks_n = get_sub_epoch_block_num(curr, self.sub_blocks)
                #   sample sub epoch
                if choose_sub_epoch(sub_epoch_blocks_n, rng, total_number_of_blocks):
                    self.log.info(f"sub epoch {sub_epoch_n - sub_epoch_reverse_idx} chosen")
                    sub_epoch_segments.extend(
                        self.create_sub_epoch_segments(
                            curr,
                            sub_epoch_blocks_n,
                            sub_epoch_n - sub_epoch_reverse_idx,
                        )
                    )
                sub_epoch_reverse_idx += 1

            if recent_blocks_n > 0:
                # add to needed reward chain recent blocks
                proof_blocks.append(header_block.reward_chain_sub_block)
                recent_blocks_n -= 1

            blocks_left -= 1

        return WeightProof(sub_epoch_data, sub_epoch_segments, proof_blocks)

    def validate_weight(
        self,
        weight_proof: WeightProof,
        prev_ses_hash: bytes32,
        fork_point_difficulty: uint64,
        fork_point_sub_slot_iters: uint64,
        fork_point_weight: uint128,
    ) -> bool:
        # sub epoch summaries validate hashes
        summaries, sub_epoch_data_weight = map_summaries(
            self.constants.SUB_EPOCH_SUB_BLOCKS,
            prev_ses_hash,
            weight_proof,
            fork_point_difficulty,
            fork_point_sub_slot_iters,
        )

        # last ses
        ses = summaries[uint32(len(summaries) - 1)]

        # validate weight
        # find first block after last sub epoch end
        self.log.info(
            f"diff {fork_point_difficulty}, sub epoch data weight {sub_epoch_data_weight}, start weight {fork_point_weight}"
        )
        block_idx = get_last_ses_block_idx(
            weight_proof.recent_reward_chain, uint128(fork_point_difficulty), sub_epoch_data_weight + fork_point_weight
        )
        if block_idx is None:
            self.log.error(f"could not find first block after last sub epoch end")
            return False
        last_ses_block = weight_proof.recent_reward_chain[block_idx]
        self.log.error(f"last ses at height {last_ses_block.sub_block_height}")
        # use block we found by weight to validate last ses_hash
        cc_vdf = weight_proof.recent_reward_chain[block_idx].challenge_chain_ip_vdf
        challenge = std_hash(
            ChallengeChainSubSlot(cc_vdf, None, std_hash(ses), ses.new_sub_slot_iters, ses.new_difficulty)
        )
        expected_challenge = weight_proof.recent_reward_chain[block_idx + 1].challenge_chain_sp_vdf.challenge
        if challenge != expected_challenge:
            self.log.error(
                f"failed to validate ses hashes block height {weight_proof.recent_reward_chain[block_idx].sub_block_height} {challenge}  {expected_challenge}"
            )
            return False

        total_challenge_blocks, total_ip_iters = uint64(0), uint64(0)
        total_slot_iters, total_slots = uint64(0), uint64(0)
        # validate sub epoch samples
        for segment in weight_proof.sub_epoch_segments:
            ses = summaries[segment.sub_epoch_n]
            ssi: uint64 = uint64(self.constants.SUB_SLOT_TIME_TARGET * ses.new_ips)
            total_slot_iters += ssi
            q_str = self.get_quality_string(segment, summaries[segment.sub_epoch_n], ssi)
            if q_str is None:
                return False

            # validate vdfs
            challenge = ses.prev_subepoch_summary_hash
            for sub_slot in segment.sub_slots:
                total_slots += 1
                vdf_info, _ = get_vdf_info_and_proof(
                    self.constants, ClassgroupElement.get_default_element(), challenge, ssi
                )
                if not validate_sub_slot_vdfs(self.constants, sub_slot, vdf_info, sub_slot.is_challenge()):
                    self.log.error("failed to validate vdfs for sub slot ")
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

        # validate recent reward chain

        return True

    def create_sub_epoch_segments(
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
            segments.append(self.handle_challenge_segment(challenge_sub_block, sub_epoch_n))

        return segments

    def handle_challenge_segment(self, block: HeaderBlock, sub_epoch_n: uint32) -> SubEpochChallengeSegment:
        sub_slots: List[SubSlotData] = []
        self.log.info(f"create challenge segment for block {block.header_hash} height {block.height} ")

        # VDFs from sub slots before challenge block
        self.log.info(f"create ip vdf for block {block.header_hash} height {block.height} ")
        first_sub_slots, end_height = self.first_sub_slots_data(block)
        sub_slots.extend(first_sub_slots)

        # VDFs from slot after challenge block to end of slot
        self.log.info(f"create slot end vdf for block {block.header_hash} height {block.height} ")
        challenge_slot_end_sub_slots = self.get_slot_end_vdf(self.header_cache[self.height_to_hash[end_height]])
        sub_slots.extend(challenge_slot_end_sub_slots)
        self.log.info(f"segment number of sub slots {len(sub_slots)}")
        return SubEpochChallengeSegment(sub_epoch_n, block.reward_chain_sub_block.reward_chain_ip_vdf, sub_slots)

    def get_slot_end_vdf(self, block: HeaderBlock) -> List[SubSlotData]:
        # get all vdfs first sub slot after challenge block to last sub slot
        curr = block
        cc_proofs: List[VDFProof] = []
        icc_proofs: List[VDFProof] = []
        sub_slots_data: List[SubSlotData] = []

        while curr.height + 1 < len(self.sub_blocks) is not None:
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
                    data = SubSlotData(
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        sub_slot.proofs.infused_challenge_chain_slot_proof,
                        sub_slot.proofs.challenge_chain_slot_proof,
                    )
                    sub_slots_data.append(data)
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
    def first_sub_slots_data(self, block: HeaderBlock) -> (List[SubSlotData], uint64):
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
                sub_slots.append(
                    SubSlotData(
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        icc_slot_vdf=sub_slot.proofs.infused_challenge_chain_slot_proof,
                        cc_slot_vdf=sub_slot.proofs.challenge_chain_slot_proof,
                    )
                )

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

    def get_quality_string(
        self,
        segment: SubEpochChallengeSegment,
        ses: SubEpochSummary,
        slot_iters: uint64,
    ):

        cc_vdf, _ = get_vdf_info_and_proof(
            self.constants, ClassgroupElement.get_default_element(), std_hash(ses), slot_iters
        )
        # get challenge
        challenge = std_hash(
            ChallengeChainSubSlot(cc_vdf, None, ses.prev_subepoch_summary_hash, ses.new_ips, ses.new_difficulty)
        )

        # find challenge block sub slot
        challenge_sub_slot = None
        for slot in segment.sub_slots:
            if slot.proof_of_space is not None:
                challenge_sub_slot = slot
                break
        # validate proof of space
        return challenge_sub_slot.proof_of_space.verify_and_get_quality_string(
            self.constants,
            challenge,
            challenge_sub_slot.cc_signage_point_sig,
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
        raise Exception("block dose not finish a sub_epoch")

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
    print("sub_epoch_blocks_n", sub_epoch_blocks_n, "total ", total_number_of_blocks)
    prob = sub_epoch_blocks_n / total_number_of_blocks
    print("try sub_epoch ", "with prob ", prob, " ", sub_epoch_blocks_n, "times")
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
    weight_proof: WeightProof,
    curr_difficulty: uint64,
    curr_sub_slot_iters: uint64,
) -> (Dict[uint32, SubEpochSummary], uint128):
    sub_epoch_data_weight: uint128 = uint128(0)
    summaries: Dict[uint32, SubEpochSummary] = {}
    for idx, sub_epoch_data in enumerate(weight_proof.sub_epochs):
        ses = SubEpochSummary(
            ses_hash,
            sub_epoch_data.reward_chain_hash,
            sub_epoch_data.num_sub_blocks_overflow,
            curr_difficulty,
            curr_sub_slot_iters,
        )

        # if new epoch update diff and iters
        if sub_epoch_data.new_sub_slot_iters is not None:
            curr_difficulty = sub_epoch_data.new_difficulty
            curr_sub_slot_iters = sub_epoch_data.new_sub_slot_iters

        print(f"map_summaries curr diff {curr_difficulty} sub_blocks_n {sub_blocks_for_se}")
        sub_epoch_data_weight += curr_difficulty * (sub_blocks_for_se + sub_epoch_data.num_sub_blocks_overflow)

        # add to dict
        summaries[idx] = ses
        ses_hash = std_hash(ses)
    return summaries, sub_epoch_data_weight


def get_last_ses_block_idx(
    recent_reward_chain: List[RewardChainSubBlock], difficulty: uint128, prev_weight: uint128
) -> Optional[uint32]:
    for idx, block in enumerate(recent_reward_chain):
        if block.weight - difficulty == prev_weight:
            return idx
    return None
