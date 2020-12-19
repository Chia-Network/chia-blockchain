import logging
import random
from typing import Dict, Optional, List, Tuple

import math

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_iterations_quality, calculate_ip_iters
from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.block_cache import BlockCache
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeChainSubSlot, RewardChainSubSlot, InfusedChallengeChainSubSlot
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


class WeightProofHandler:

    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 10  # todo switch to 256 after testing / segment size resolved
    WeightProofHandler = "weight_proof_handler"

    def __init__(
        self,
        constants: ConsensusConstants,
        block_cache: BlockCache,
        name: str = None,
    ):
        self.proof: Optional[Tuple[bytes32, WeightProof]] = None
        self.constants = constants
        self.block_cache = block_cache
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(self.WeightProofHandler)

    def set_block_cache(self, block_cache):
        self.block_cache = block_cache

    async def get_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        if self.proof is not None and tip == self.proof[0]:
            wp: Optional[WeightProof] = self.proof[1]
            return wp
        wp = await self.create_proof_of_weight(tip)
        if wp is None:
            return None
        self.proof = (tip, wp)
        return wp

    async def create_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        """
        Creates a weight proof object
        """
        assert self.block_cache is not None
        # todo clean some of the logs after tests pass
        sub_epoch_data: List[SubEpochData] = []
        sub_epoch_segments: List[SubEpochChallengeSegment] = []
        rng: random.Random = random.Random(tip)
        # ses_hash from the latest sub epoch summary before this part of the chain
        tip = self.block_cache.sub_block_record(tip)
        if tip is None:
            self.log.error(f"build weight proof, for unknown peak  {tip}")
            return None
        tip_height = tip.sub_block_height
        sub_epoch_n = uint32(0)

        recent_reward_chain = await self.get_recent_chain(tip_height)
        if recent_reward_chain is None:
            self.log.info("failed adding recent chain")
            return None

        weight_to_check = self.get_weights_for_sampling(rng, tip.weight, recent_reward_chain)
        if weight_to_check is None:
            self.log.warning("math error while sampling sub epochs")

        for ses_height in self.block_cache.get_ses_heights():
            # next sub block
            sub_block = self.block_cache.height_to_sub_block_record(ses_height)
            if sub_block is None or sub_block.sub_epoch_summary_included is None:
                self.log.error("error while building proof")
                return None

            self.log.debug(f"sub epoch end, block height {ses_height} {sub_block.sub_epoch_summary_included}")
            sub_epoch_data.append(make_sub_epoch_data(sub_block.sub_epoch_summary_included))
            # get sub_epoch_blocks_n in sub_epoch
            sub_epoch_blocks_n = get_sub_epoch_block_num(sub_block, self.block_cache)
            if sub_epoch_blocks_n is None:
                self.log.error("could not get sub epoch block number")
                return None

            start_of_epoch = self.block_cache.height_to_sub_block_record(uint32(ses_height - sub_epoch_blocks_n))

            # if we have enough sub_epoch samples, dont sample
            if sub_epoch_n >= self.MAX_SAMPLES:
                continue

            # sample sub epoch
            if self.sample_sub_epoch(start_of_epoch, sub_block, weight_to_check):
                self.log.debug(f"sample: {sub_epoch_n}")
                segments = await self.__create_sub_epoch_segments(sub_block, sub_epoch_blocks_n, sub_epoch_n)
                if segments is None:
                    self.log.error(f"failed while building segments for sub epoch {sub_epoch_n} ")
                    return None
                sub_epoch_segments.extend(segments)
                sub_epoch_n = uint32(sub_epoch_n + 1)

        self.log.info(f"sub_epochs: {len(sub_epoch_data)}")
        return WeightProof(sub_epoch_data, sub_epoch_segments, recent_reward_chain)

    def sample_sub_epoch(self, start_of_epoch, end_of_epoch, weight_to_check) -> bool:
        if weight_to_check is None:
            return True
        choose = False
        for weight in weight_to_check:
            if start_of_epoch.weight < weight < end_of_epoch.weight:
                self.log.debug(f"start weight: {start_of_epoch.weight}")
                self.log.debug(f"weight to check {weight}")
                self.log.debug(f"end weight: {end_of_epoch.weight}")
                choose = True
                break

        return choose

    async def get_recent_chain(self, tip_height: uint32) -> Optional[List[ProofBlockHeader]]:
        recent_chain: List[ProofBlockHeader] = []
        start_height = uint32(tip_height - self.constants.WEIGHT_PROOF_RECENT_BLOCKS)

        await self.block_cache.init_headers(uint32(tip_height - self.constants.WEIGHT_PROOF_RECENT_BLOCKS), tip_height)
        while start_height <= tip_height:
            # add to needed reward chain recent blocks
            header_block = await self.block_cache.height_to_header_block(start_height)
            if header_block is None:
                return None
            recent_chain.append(ProofBlockHeader(header_block.finished_sub_slots, header_block.reward_chain_sub_block))
            start_height = start_height + uint32(1)  # type: ignore

        return recent_chain

    def validate_weight_proof(self, weight_proof: WeightProof) -> Tuple[bool, uint32]:
        # sub epoch summaries validate hashes
        assert self.block_cache is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)

        self.log.info("validate weight proof")
        summaries = self.validate_sub_epoch_summaries(weight_proof)
        if summaries is None:
            return False, uint32(0)

            # self.log.info(f"validate sub epoch challenge segments")
            # if not self._validate_segments(weight_proof, summaries, curr):
            #     return False

        self.log.debug("validate weight proof recent blocks")
        if not self._validate_recent_blocks(weight_proof):
            return False, uint32(0)

        return True, self.get_fork_point(summaries)

    def _validate_recent_blocks(self, weight_proof: WeightProof):
        return True

    def validate_sub_epoch_summaries(
        self,
        weight_proof: WeightProof,
    ) -> Optional[List[SubEpochSummary]]:
        assert self.block_cache is not None

        summaries, sub_epoch_data_weight = map_summaries(
            self.constants.SUB_EPOCH_SUB_BLOCKS,
            self.constants.GENESIS_SES_HASH,
            weight_proof.sub_epochs,
            self.constants.DIFFICULTY_STARTING,
        )

        self.log.info(f"validating {len(summaries)} summaries")

        last_ses = summaries[-1]
        last_ses_block = get_last_ses_block_idx(self.constants, weight_proof.recent_chain_data)
        if last_ses_block is None:
            self.log.error("could not find first block after last sub epoch end")
            return None
        # validate weight

        # validate last ses_hash
        if last_ses.get_hash() != last_ses_block.finished_sub_slots[-1].challenge_chain.subepoch_summary_hash:
            self.log.error(
                f"failed to validate ses hashes block height {last_ses_block.reward_chain_sub_block.sub_block_height}"
            )
            return None
        return summaries

    def validate_segments(
        self,
        weight_proof: WeightProof,
        summaries: Dict[uint32, SubEpochSummary],
        curr_ssi: uint64,
        rc_sub_slot_hash: bytes32,
    ):
        # total_challenge_blocks, total_ip_iters = uint64(0), uint64(0)
        total_slot_iters, total_slots = uint64(0), uint64(0)
        total_ip_iters = uint64(0)
        # validate sub epoch samples
        cc_sub_slot: Optional[ChallengeChainSubSlot] = None
        curr_sub_epoch_n = -1

        for idx, segment in enumerate(weight_proof.sub_epoch_segments):
            if curr_sub_epoch_n < segment.sub_epoch_n:
                self.log.info(f"handle new sub epoch {segment.sub_epoch_n}")

                # recreate RewardChainSubSlot for next ses rc_hash
                # get last slot of prev segment
                if curr_sub_epoch_n != -1:
                    rc_sub_slot, cc_sub_slot, icc_sub_slot = self.get_rc_sub_slot_hash(
                        weight_proof.sub_epoch_segments[idx - 1], summaries
                    )
                    rc_sub_slot_hash = rc_sub_slot.get_hash()

                self.log.info("compare segment rc_sub_slot_hash with ses reward_chain_hash")
                if not summaries[segment.sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
                    self.log.error(f"failed reward_chain_hash validation sub_epoch {segment.sub_epoch_n}")
                    self.log.error(f"rc slot hash  {rc_sub_slot_hash}")
                    return False

                self.log.info(f"validating segment {idx}")
                assert cc_sub_slot is not None
                valid_segment, total_slot_iters, total_slots, challenge_blocks = self._validate_segment_slots(
                    summaries, segment, curr_ssi, total_slot_iters, total_slots, total_ip_iters, cc_sub_slot
                )

                # if not valid_segment:
                #     self.log.error(f"failed to validate segment {idx} of sub_epoch {segment.sub_epoch_n} slots")
                #     return False

                # total_challenge_blocks += challenge_blocks
            curr_sub_epoch_n = segment.sub_epoch_n

        # avg_ip_iters = total_ip_iters / total_challenge_blocks
        # avg_slot_iters = total_slot_iters / total_slots
        # if avg_slot_iters / avg_ip_iters < float(self.constants.WEIGHT_PROOF_THRESHOLD):
        #     self.log.error(f"bad avg challenge block positioning ration: {avg_slot_iters / avg_ip_iters}")
        #     return False

        return True

    def get_rc_sub_slot_hash(
        self,
        segment: SubEpochChallengeSegment,
        summaries: Dict[uint32, SubEpochSummary],
    ) -> Tuple[RewardChainSubSlot, ChallengeChainSubSlot, InfusedChallengeChainSubSlot]:

        ses = summaries[segment.sub_epoch_n]
        first_slot = segment.sub_slots[0]
        assert first_slot.icc_slot_end_info is not None
        assert first_slot.cc_slot_end_info is not None
        icc_sub_slot = InfusedChallengeChainSubSlot(first_slot.icc_slot_end_info)

        cc_sub_slot = ChallengeChainSubSlot(
            first_slot.cc_slot_end_info,
            icc_sub_slot.get_hash(),
            ses.get_hash(),
            ses.new_sub_slot_iters,
            ses.new_difficulty,
        )
        deficit: uint8 = self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
        if summaries[uint32(segment.sub_epoch_n + 1)].num_sub_blocks_overflow == 0:
            deficit = uint8(deficit - 1)  # no overflow in start of sub epoch

        assert first_slot.rc_slot_end_info is not None
        rc_sub_slot = RewardChainSubSlot(
            first_slot.rc_slot_end_info,
            cc_sub_slot.get_hash(),
            icc_sub_slot.get_hash(),
            uint8(deficit),  # -1 if no overflows in start of sub_epoch
        )

        return rc_sub_slot, cc_sub_slot, icc_sub_slot

    async def __create_sub_epoch_segments(
        self, block: SubBlockRecord, sub_epoch_blocks_n: uint32, sub_epoch_n: uint32
    ) -> Optional[List[SubEpochChallengeSegment]]:
        """
        receives the last block in sub epoch and creates List[SubEpochChallengeSegment] for that sub_epoch
        """
        # get headers in cache
        await self.block_cache.init_headers(
            uint32(block.sub_block_height - sub_epoch_blocks_n), uint32(block.sub_block_height + 30)
        )
        segments: List[SubEpochChallengeSegment] = []
        curr: Optional[SubBlockRecord] = block
        assert self.block_cache is not None
        last_slot_hb = await self.block_cache.header_block(block.header_hash)
        if last_slot_hb is None:
            self.log.error(f"could not find block height {block.height} ")
            return None
        assert last_slot_hb.finished_sub_slots is not None

        count: uint32 = sub_epoch_blocks_n
        while not count == 0:
            # not challenge block skip
            assert curr is not None
            if curr.is_challenge_sub_block(self.constants):
                self.log.debug(f"sub epoch {sub_epoch_n} challenge segment, starts at {curr.sub_block_height} ")
                seg = await self._handle_challenge_segment(curr, sub_epoch_n)
                if seg is None:
                    self.log.error(f"failed creating segment {curr.header_hash} ")
                    return None
                segments.insert(0, seg)

            assert curr is not None
            curr = self.block_cache.sub_block_record(curr.prev_hash)
            if curr is None:
                self.log.error("could not find block record")
            count = uint32(count - 1)
        return segments

    async def _handle_challenge_segment(
        self, block_rec: SubBlockRecord, sub_epoch_n: uint32
    ) -> Optional[SubEpochChallengeSegment]:
        assert self.block_cache is not None
        sub_slots: List[SubSlotData] = []
        self.log.debug(
            f"create challenge segment for block {block_rec.header_hash} sub_block_height {block_rec.sub_block_height} "
        )
        block_header = await self.block_cache.header_block(block_rec.header_hash)
        if block_header is None:
            self.log.error("could not find challenge_sub_block in cache")
            return None

        # VDFs from sub slots before challenge block
        self.log.debug(f"create ip vdf for block {block_header.header_hash} height {block_header.sub_block_height} ")
        first_sub_slots, end_height = await self.__first_sub_slots_data(block_header)
        if first_sub_slots is None or end_height is None:
            self.log.error("failed building first sub slots")
            return None

        sub_slots.extend(first_sub_slots)

        # # VDFs from slot after challenge block to end of slot
        self.log.debug(
            f"create slot end vdf for block {block_header.header_hash} height {block_header.sub_block_height} "
        )

        end_height_hb = await self.block_cache.height_to_header_block(end_height)
        if end_height_hb is None:
            self.log.error(f"could not find block height {end_height}")
            return None
        challenge_slot_end_sub_slots = await self.__get_slot_end_vdf(end_height_hb)
        if challenge_slot_end_sub_slots is None:
            self.log.error("failed building slot end ")
            return None
        sub_slots.extend(challenge_slot_end_sub_slots)
        self.log.debug(f"segment number of sub slots {len(sub_slots)}")
        return SubEpochChallengeSegment(sub_epoch_n, block_header.reward_chain_sub_block.reward_chain_ip_vdf, sub_slots)

    async def __get_slot_end_vdf(self, block: HeaderBlock) -> Optional[List[SubSlotData]]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        assert self.block_cache is not None
        curr: Optional[HeaderBlock] = block
        assert curr is not None
        cc_proofs: List[VDFProof] = []
        icc_proofs: List[VDFProof] = []
        sub_slots_data: List[SubSlotData] = []
        max_height = self.block_cache.max_height()
        while curr.sub_block_height < max_height:
            prev = curr
            curr = await self.block_cache.height_to_header_block(curr.sub_block_height + 1)
            if curr is None:
                self.log.error(f"could not find block height {prev.sub_block_height}  ")
                return None
            if len(curr.finished_sub_slots) > 0:
                # slot finished combine proofs and add slot data to list
                sub_slots_data.append(
                    SubSlotData(
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        combine_proofs(cc_proofs),
                        combine_proofs(icc_proofs),
                        None,
                        None,
                        None,
                    )
                )

                # handle finished empty sub slots
                for sub_slot in curr.finished_sub_slots:
                    sub_slots_data.append(empty_sub_slot_data(sub_slot))
                    if sub_slot.reward_chain.deficit == self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        # end of challenge slot
                        break

                # new sub slot
                cc_proofs = []

            # append sub slot proofs
            if curr.infused_challenge_chain_ip_proof is not None:
                icc_proofs.append(curr.infused_challenge_chain_ip_proof)
            if curr.challenge_chain_sp_proof is not None:
                cc_proofs.append(curr.challenge_chain_sp_proof)
            if curr.challenge_chain_ip_proof is not None:
                cc_proofs.append(curr.challenge_chain_ip_proof)

        return sub_slots_data

    # returns a challenge chain vdf from slot start to signage point
    async def __first_sub_slots_data(self, block: HeaderBlock) -> Tuple[Optional[List[SubSlotData]], uint32]:
        # combine cc vdfs of all reward blocks from the start of the sub slot to end
        assert self.block_cache is not None
        sub_slots: List[SubSlotData] = []
        # todo vdf of the overflow blocks before the challenge block ?
        # get all finished sub slots
        if len(block.finished_sub_slots) > 0:
            for sub_slot in block.finished_sub_slots:
                sub_slots.append(empty_sub_slot_data(sub_slot))

        curr = self.block_cache.height_to_sub_block_record(block.sub_block_height + 1)
        if curr is None:
            self.log.error("could not find block record in cache")
            return None, uint32(0)

        next_slot_height: uint32 = uint32(0)
        cc_slot_end_vdf: List[VDFProof] = []
        icc_slot_end_vdf: List[VDFProof] = []
        while not curr.first_in_sub_slot:
            curr = self.block_cache.height_to_sub_block_record(uint32(curr.sub_block_height + 1))
            if curr is None:
                self.log.error("sub block rec is not in cache")
                return None, uint32(0)
            curr_header = await self.block_cache.header_block(curr.header_hash)
            if curr_header is None:
                self.log.error("header block rec is not in cache")
                return None, uint32(0)
            next_slot_height = self._handle_finished_slots(
                cc_slot_end_vdf, curr, curr_header, icc_slot_end_vdf, sub_slots
            )

            if curr_header.challenge_chain_sp_proof is not None:
                cc_slot_end_vdf.append(curr_header.challenge_chain_sp_proof)
            if curr_header.challenge_chain_sp_proof is not None:
                cc_slot_end_vdf.append(curr_header.challenge_chain_ip_proof)
            if curr_header.infused_challenge_chain_ip_proof is not None:
                icc_slot_end_vdf.append(curr_header.infused_challenge_chain_ip_proof)

        sub_slots.append(
            SubSlotData(
                block.reward_chain_sub_block.proof_of_space,
                block.reward_chain_sub_block.challenge_chain_sp_signature,
                block.challenge_chain_sp_proof,
                block.challenge_chain_ip_proof,
                block.reward_chain_sub_block.challenge_chain_sp_vdf,
                block.reward_chain_sub_block.signage_point_index,
                combine_proofs(cc_slot_end_vdf),
                combine_proofs(icc_slot_end_vdf),
                None,
                None,
                None,
            )
        )

        return sub_slots, next_slot_height

    def _handle_finished_slots(self, cc_slot_end_vdf, curr, curr_header, icc_slot_end_vdf, sub_slots):
        if curr_header.finished_sub_slots is None or not len(curr_header.finished_sub_slots) > 0:
            return

        icc_vdf: Optional[VDFInfo] = None
        if curr_header.finished_sub_slots[-1].infused_challenge_chain is not None:
            icc_vdf = curr_header.finished_sub_slots[-1].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
        next_slot_height = uint32(curr.sub_block_height + 1)
        sub_slots.append(
            SubSlotData(
                None,
                None,
                None,
                None,
                None,
                None,
                combine_proofs(cc_slot_end_vdf),
                combine_proofs(icc_slot_end_vdf),
                curr_header.finished_sub_slots[-1].challenge_chain.challenge_chain_end_of_slot_vdf,
                icc_vdf,
                curr_header.finished_sub_slots[-1].reward_chain.end_of_slot_vdf,
            )
        )
        return next_slot_height

    def __get_quality_string(
        self, segment: SubEpochChallengeSegment, idx: int, ses: SubEpochSummary
    ) -> Optional[bytes32]:

        # find challenge block sub slot
        challenge_sub_slot: SubSlotData = segment.sub_slots[idx]

        cc_vdf = segment.sub_slots[idx - 1].cc_slot_end_info
        icc_vdf = segment.sub_slots[idx - 1].icc_slot_end_info
        assert cc_vdf is not None and icc_vdf is not None
        cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_vdf.get_hash(), None, None, None)
        challenge = cc_sub_slot.get_hash()

        if challenge_sub_slot.cc_sp_vdf_info is None:
            self.log.info(f"challenge from prev slot {challenge_sub_slot.cc_sp_vdf_info}")
            cc_sp_hash: bytes32 = cc_sub_slot.get_hash()
        else:
            self.log.info(f"challenge from sp vdf {challenge_sub_slot.cc_sp_vdf_info}")
            cc_sp_hash = challenge_sub_slot.cc_sp_vdf_info.output.get_hash()
        # validate proof of space
        assert challenge_sub_slot.proof_of_space is not None
        return challenge_sub_slot.proof_of_space.verify_and_get_quality_string(
            self.constants,
            challenge,
            cc_sp_hash,
        )

    def _validate_segment_slots(
        self,
        summaries: Dict[uint32, SubEpochSummary],
        segment: SubEpochChallengeSegment,
        curr_ssi: uint64,
        total_slot_iters: uint64,
        total_slots: uint64,
        total_ip_iters: uint64,
        cc_sub_slot: ChallengeChainSubSlot,
    ) -> Tuple[bool, uint64, uint64, int]:
        ses = summaries[segment.sub_epoch_n]
        challenge_blocks = 0
        if ses.new_sub_slot_iters is not None:
            curr_ssi = ses.new_sub_slot_iters
        for idx, sub_slot in enumerate(segment.sub_slots):
            total_slot_iters = total_slot_iters + curr_ssi  # type: ignore
            total_slots = total_slots + uint64(1)  # type: ignore

            # todo uncomment after vdf merging is done
            # if not validate_sub_slot_vdfs(self.constants, sub_slot, vdf_info, sub_slot.is_challenge()):
            #     self.log.info(f"failed to validate {idx} sub slot vdfs")
            #     return False

            if sub_slot.is_challenge():
                self.log.info("validate proof of space")
                q_str = self.__get_quality_string(segment, idx, ses)
                if q_str is None:
                    self.log.error("failed to validate segment space proof")
                    return False, uint64(0), uint64(0), 0
                assert sub_slot is not None
                assert cc_sub_slot is not None
                assert sub_slot.cc_signage_point_index is not None
                assert sub_slot.cc_signage_point is not None
                assert sub_slot.proof_of_space is not None
                required_iters: uint64 = calculate_iterations_quality(
                    q_str,
                    sub_slot.proof_of_space.size,
                    cc_sub_slot.get_hash(),
                    sub_slot.cc_signage_point.get_hash(),
                )
                total_ip_iters = total_ip_iters + calculate_ip_iters(  # type: ignore
                    self.constants, curr_ssi, sub_slot.cc_signage_point_index, required_iters
                )
                challenge_blocks = challenge_blocks + 1

        return True, total_slot_iters, total_slots, challenge_blocks

    def get_fork_point(self, received_summaries: List[SubEpochSummary]) -> uint32:
        # iterate through sub epoch summaries to find fork point
        fork_point_index = 0
        ses_heights = self.block_cache.get_ses_heights()
        for idx, summary_height in enumerate(ses_heights):
            self.log.info(f"check summary {idx} height {summary_height}")
            local_ses = self.block_cache.get_ses(summary_height)
            if local_ses is None or local_ses.get_hash() != received_summaries[idx].get_hash():
                break
            fork_point_index = idx

        if fork_point_index > 2:
            # Two summeries can have different blocks and still be identical
            # This gets resolved after one full sub epoch
            height = ses_heights[fork_point_index - 2]
        else:
            height = 0

        return height

    def get_weights_for_sampling(
        self, rng: random.Random, total_weight: uint128, recent_chain: List[ProofBlockHeader]
    ) -> Optional[List[uint128]]:
        weight_to_check = []
        last_l_weight = recent_chain[-1].reward_chain_sub_block.weight - recent_chain[0].reward_chain_sub_block.weight
        delta = last_l_weight / total_weight
        prob_of_adv_succeeding = 1 - math.log(self.C, delta)
        if prob_of_adv_succeeding == 0:
            return None
        queries = -self.LAMBDA_L * math.log(2, prob_of_adv_succeeding)
        for i in range(int(queries) + 1):
            u = rng.random()
            q = 1 - delta ** u
            # todo check division and type conversions
            weight = q * float(total_weight)
            weight_to_check.append(uint128(weight))
        return weight_to_check


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


def get_sub_epoch_block_num(ses_block: SubBlockRecord, cache: BlockCache) -> Optional[uint32]:
    """
    returns the number of blocks in a sub epoch ending with
    """

    count: uint32 = uint32(0)
    # count from end of sub_epoch
    if ses_block.sub_epoch_summary_included is None:
        return None

    curr = cache.sub_block_record(ses_block.prev_hash)
    if curr is None:
        return None

    if ses_block.overflow:
        count = count + uint32(1)  # type: ignore

    while not curr.sub_epoch_summary_included and curr is not None:
        # todo skip overflows from last sub epoch
        if curr.sub_block_height == uint32(0):
            return count

        curr = cache.sub_block_record(curr.prev_hash)
        if curr is None:
            return None
        count = count + uint32(1)  # type: ignore

    if curr.overflow:
        count = count - 1  # type: ignore

    return count


def validate_sub_slot_vdfs(
    constants: ConsensusConstants, sub_slot: SubSlotData, vdf_info: VDFInfo, infused: bool
) -> bool:
    default = ClassgroupElement.get_default_element()
    if infused:
        assert sub_slot.cc_sp_vdf_info is not None
        assert sub_slot.cc_signage_point is not None
        if not sub_slot.cc_signage_point.is_valid(constants, default, sub_slot.cc_sp_vdf_info):
            return False
        # todo fix to correct vdf input
        assert sub_slot.cc_infusion_point is not None
        if not sub_slot.cc_infusion_point.is_valid(constants, default, vdf_info):
            return False

        assert sub_slot.cc_slot_end is not None
        assert sub_slot.cc_slot_end_info is not None
        if not sub_slot.cc_slot_end.is_valid(constants, default, sub_slot.cc_slot_end_info):
            return False
        assert sub_slot.icc_slot_end_info is not None
        assert sub_slot.icc_slot_end is not None
        if not sub_slot.icc_slot_end.is_valid(constants, default, sub_slot.icc_slot_end_info):
            return False
        return True
    assert sub_slot.cc_slot_end is not None
    return sub_slot.cc_slot_end.is_valid(constants, ClassgroupElement.get_default_element(), vdf_info)


def map_summaries(
    sub_blocks_for_se: uint32,
    ses_hash: bytes32,
    sub_epoch_data: List[SubEpochData],
    curr_difficulty: uint64,
) -> Tuple[List[SubEpochSummary], uint128]:
    sub_epoch_data_weight: uint128 = uint128(0)
    summaries: List[SubEpochSummary] = []

    for idx, data in enumerate(sub_epoch_data):
        ses = SubEpochSummary(
            ses_hash,
            data.reward_chain_hash,
            data.num_sub_blocks_overflow,
            data.new_difficulty,
            data.new_sub_slot_iters,
        )

        # if new epoch update diff and iters
        if data.new_difficulty is not None:
            curr_difficulty = data.new_difficulty

        sub_epoch_data_weight = sub_epoch_data_weight + uint128(  # type: ignore
            curr_difficulty * (sub_blocks_for_se + data.num_sub_blocks_overflow)
        )

        # add to dict
        summaries.append(ses)
        ses_hash = std_hash(ses)
    return summaries, sub_epoch_data_weight


def get_last_ses_block_idx(
    constants: ConsensusConstants, recent_reward_chain: List[ProofBlockHeader]
) -> Optional[ProofBlockHeader]:
    for idx, block in enumerate(reversed(recent_reward_chain)):
        if (block.reward_chain_sub_block.sub_block_height % constants.SUB_EPOCH_SUB_BLOCKS) == 0:
            idx = len(recent_reward_chain) - 1 - idx  # reverse
            # find first block after sub slot end
            while idx < len(recent_reward_chain):
                curr = recent_reward_chain[idx]
                if len(curr.finished_sub_slots) > 0:
                    for slot in curr.finished_sub_slots:
                        if slot.challenge_chain.subepoch_summary_hash is not None:
                            return curr
                idx += 1
    return None


def empty_sub_slot_data(end_of_slot: EndOfSubSlotBundle):
    icc_end_of_slot_info: Optional[VDFInfo] = None
    if end_of_slot.infused_challenge_chain is not None:
        icc_end_of_slot_info = end_of_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
    return SubSlotData(
        None,
        None,
        None,
        None,
        None,
        None,
        end_of_slot.proofs.challenge_chain_slot_proof,
        end_of_slot.proofs.infused_challenge_chain_slot_proof,
        end_of_slot.challenge_chain.challenge_chain_end_of_slot_vdf,
        icc_end_of_slot_info,
        end_of_slot.reward_chain.end_of_slot_vdf,
    )
