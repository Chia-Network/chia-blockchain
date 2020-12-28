import asyncio
import logging
import random
from typing import Optional, List, Tuple

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
        self.tip: Optional[bytes32] = None
        self.proof: Optional[WeightProof] = None
        self.constants = constants
        self.block_cache = block_cache
        self.lock = asyncio.Lock()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(self.WeightProofHandler)

    async def get_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:

        tip_rec = self.block_cache.sub_block_record(tip)
        if tip_rec is None:
            self.log.error("unknown tip")
            return None

        if tip_rec.sub_block_height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            self.log.debug("chain to short for weight proof")
            return None
        curr: Optional[SubBlockRecord] = tip_rec
        await self.lock.acquire()
        if self.proof is not None:
            if tip == self.tip:
                self.lock.release()
                return self.proof
            recent_chain_start = self.proof.recent_chain_data[0].reward_chain_sub_block.sub_block_height
            while curr is not None:
                if curr.sub_block_height < recent_chain_start:
                    self.log.info("this peak is on a fork longer then recent proof chain")
                    break
                if curr.header_hash == self.tip:
                    new_wp = await self._extend_proof_of_weight(self.proof, tip_rec)
                    self.proof = new_wp
                    self.tip = tip
                    self.lock.release()
                    return new_wp
                curr = self.block_cache.sub_block_record(curr.prev_hash)
                if curr is None:
                    self.lock.release()
                    return None

        wp = await self._create_proof_of_weight(tip)
        if wp is None:
            self.lock.release()
            return None
        self.proof = wp
        self.tip = tip
        self.lock.release()
        return wp

    async def _extend_proof_of_weight(
        self, weight_proof: WeightProof, new_tip: SubBlockRecord
    ) -> Optional[WeightProof]:
        # replace recent chain

        self.log.info(f"extend weight proof peak {new_tip.header_hash} {new_tip.sub_block_height}")

        recent_chain = await self._get_recent_chain(new_tip.sub_block_height, weight_proof)
        if recent_chain is None:
            return None
        end_height = weight_proof.recent_chain_data[-1].reward_chain_sub_block.sub_block_height
        sub_epoch_data = weight_proof.sub_epochs
        for summary in self.block_cache.get_ses_from_height(end_height):
            sub_epoch_data.append(_make_sub_epoch_data(summary))

        # todo handle new sampling
        return WeightProof(sub_epoch_data, weight_proof.sub_epoch_segments, recent_chain)

    async def _create_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        """
        Creates a weight proof object
        """
        assert self.block_cache is not None
        sub_epoch_data: List[SubEpochData] = []
        sub_epoch_segments: List[SubEpochChallengeSegment] = []
        tip_rec = self.block_cache.sub_block_record(tip)
        if tip_rec is None:
            self.log.error("failed not tip in cache")
            return None
        self.log.info(f"create weight proof peak {tip} {tip_rec.sub_block_height}")
        recent_chain = await self._get_recent_chain(tip_rec.sub_block_height)
        if recent_chain is None:
            return None

        weight_to_check = self._get_weights_for_sampling(random.Random(tip), tip_rec.weight, recent_chain)
        if weight_to_check is None:
            self.log.warning("math error while sampling sub epochs")

        prev_ses_block = self.block_cache.height_to_sub_block_record(uint32(0))
        if prev_ses_block is None:
            return None

        sub_epoch_n = uint32(0)
        summary_heights = self.block_cache.get_ses_heights()
        for idx, ses_height in enumerate(summary_heights):
            # next sub block
            ses_block = self.block_cache.height_to_sub_block_record(ses_height)
            if ses_block is None or ses_block.sub_epoch_summary_included is None:
                self.log.error("error while building proof")
                return None

            self.log.info(f"handle sub epoch summary at height: {ses_height} weight: {ses_block.weight}")
            sub_epoch_data.append(_make_sub_epoch_data(ses_block.sub_epoch_summary_included))

            # if we have enough sub_epoch samples, dont sample
            if sub_epoch_n >= self.MAX_SAMPLES:
                self.log.debug("reached sampled sub epoch cap")
                continue

            # sample sub epoch
            if self._sample_sub_epoch(prev_ses_block, ses_block, weight_to_check):  # type: ignore
                segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(idx))
                if segments is None:
                    self.log.error(f"failed while building segments for sub epoch {idx}, ses height {ses_height} ")
                    return None
                self.log.debug(f"sub epoch {sub_epoch_n} has {len(segments)} segments")
                sub_epoch_segments.extend(segments)
                sub_epoch_n = uint32(sub_epoch_n + 1)
            prev_ses_block = ses_block
        self.log.info(f"sub_epochs: {len(sub_epoch_data)}")
        return WeightProof(sub_epoch_data, sub_epoch_segments, recent_chain)

    def _sample_sub_epoch(
        self, start_of_epoch: SubBlockRecord, end_of_epoch: SubBlockRecord, weight_to_check: List[uint128]
    ) -> bool:
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

    async def _get_recent_chain(
        self, tip_height: uint32, wp: Optional[WeightProof] = None
    ) -> Optional[List[ProofBlockHeader]]:
        recent_chain: List[ProofBlockHeader] = []

        curr_height = uint32(tip_height - self.constants.WEIGHT_PROOF_RECENT_BLOCKS)

        if wp is not None:
            idx = 0
            for block in wp.recent_chain_data:
                if block.reward_chain_sub_block.sub_block_height == curr_height:
                    break
                idx += 1

            while curr_height <= wp.recent_chain_data[-1].reward_chain_sub_block.sub_block_height:
                recent_chain.append(wp.recent_chain_data[idx])
                curr_height = curr_height + uint32(1)  # type: ignore
                idx += 1

        await self.block_cache.init_headers(curr_height, tip_height)

        while curr_height <= tip_height:
            # add to needed reward chain recent blocks
            header_block = await self.block_cache.height_to_header_block(curr_height)
            if header_block is None:
                self.log.error("creating recent chain failed")
                return None
            recent_chain.append(ProofBlockHeader(header_block.finished_sub_slots, header_block.reward_chain_sub_block))
            curr_height = curr_height + uint32(1)  # type: ignore

        self.log.info(
            f"recent chain, "
            f"start: {recent_chain[0].reward_chain_sub_block.sub_block_height} "
            f"end:  {recent_chain[-1].reward_chain_sub_block.sub_block_height} "
        )
        return recent_chain

    def validate_weight_proof(self, weight_proof: WeightProof) -> Tuple[bool, uint32]:
        # sub epoch summaries validate hashes
        assert self.block_cache is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)

        self.log.info("validate weight proof")
        summaries = self._validate_sub_epoch_summaries(weight_proof)
        if summaries is None:
            self.log.warning("weight proof failed sub epoch data validation")
            return False, uint32(0)

        self.log.info("validate sub epoch challenge segments")
        if not self._validate_segments(weight_proof, summaries):
            return False, uint32(0)

        self.log.debug("validate weight proof recent blocks")
        if not self._validate_recent_blocks(weight_proof):
            return False, uint32(0)

        return True, self.get_fork_point(summaries)

    def _validate_recent_blocks(self, weight_proof: WeightProof):
        return True

    def _validate_sub_epoch_summaries(
        self,
        weight_proof: WeightProof,
    ) -> Optional[List[SubEpochSummary]]:
        assert self.block_cache is not None

        last_ses_block = _get_last_ses_block_idx(self.constants, weight_proof.recent_chain_data)
        if last_ses_block is None:
            self.log.warning("could not find last ses block")
            return None

        summaries, sub_epoch_data_weight = _map_summaries(
            self.constants.SUB_EPOCH_SUB_BLOCKS,
            self.constants.GENESIS_SES_HASH,
            weight_proof.sub_epochs,
            self.constants.DIFFICULTY_STARTING,
        )

        self.log.info(f"validating {len(summaries)} summaries")

        # validate weight
        if not self._validate_summaries_weight(sub_epoch_data_weight, summaries, weight_proof):
            self.log.error("failed validating weight")
            return None

        last_ses = summaries[-1]
        self.log.info(f"last ses height {last_ses_block.reward_chain_sub_block.sub_block_height}")
        # validate last ses_hash
        if last_ses.get_hash() != last_ses_block.finished_sub_slots[-1].challenge_chain.subepoch_summary_hash:
            self.log.error(
                f"failed to validate ses hashes block height {last_ses_block.reward_chain_sub_block.sub_block_height}"
            )
            return None
        return summaries

    def _validate_summaries_weight(self, sub_epoch_data_weight, summaries, weight_proof) -> bool:
        num_over = summaries[-1].num_sub_blocks_overflow
        ses_end_height = (len(summaries) - 1) * self.constants.SUB_EPOCH_SUB_BLOCKS + num_over - 1
        self.log.info(f"weight height {ses_end_height}")
        curr = None
        for block in weight_proof.recent_chain_data:
            if block.reward_chain_sub_block.sub_block_height == ses_end_height:
                curr = block
        if curr is None:
            return False

        return curr.reward_chain_sub_block.weight == sub_epoch_data_weight

    def _validate_segments(
        self,
        weight_proof: WeightProof,
        summaries: List[SubEpochSummary],
    ):
        rc_sub_slot_hash = self.constants.FIRST_CC_CHALLENGE
        curr_difficulty = self.constants.DIFFICULTY_STARTING
        curr_ssi = self.constants.SUB_SLOT_ITERS_STARTING
        total_blocks, total_ip_iters = 0, 0
        total_slot_iters, total_slots = 0, 0
        total_ip_iters = 0
        curr_sub_epoch_n = -1
        prev_ses: Optional[SubEpochSummary] = None
        for idx, segment in enumerate(weight_proof.sub_epoch_segments):
            if curr_sub_epoch_n < segment.sub_epoch_n:
                self.log.info(f"handle sub epoch {segment.sub_epoch_n}")
                # recreate RewardChainSubSlot for next ses rc_hash
                if segment.sub_epoch_n > 0:
                    rc_sub_slot_hash = self.__get_rc_sub_slot_hash(segment, summaries).get_hash()
                    prev_ses = summaries[segment.sub_epoch_n - 1]
                    curr_difficulty, curr_ssi = self._get_current_vars(segment.sub_epoch_n, summaries)

                self.log.debug("compare segment rc_sub_slot_hash with ses reward_chain_hash")
                if not summaries[segment.sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
                    self.log.error(f"failed reward_chain_hash validation sub_epoch {segment.sub_epoch_n}")
                    return False

            valid_segment, ip_iters, slot_iters, slots, blocks = self._validate_segment_slots(
                segment,
                curr_ssi,
                curr_difficulty,
                prev_ses,
                None if idx == 0 else weight_proof.sub_epoch_segments[idx - 1].sub_slots[-1],
            )
            prev_ses = None
            if not valid_segment:
                self.log.error(f"failed to validate segment {idx} of sub_epoch {segment.sub_epoch_n} slots")
                return False

            total_blocks += blocks
            total_slot_iters += slot_iters
            total_slots += slots
            total_ip_iters += ip_iters

            curr_sub_epoch_n = segment.sub_epoch_n
        avg_ip_iters = total_ip_iters / total_blocks
        avg_slot_iters = total_slot_iters / total_slots
        if avg_slot_iters / avg_ip_iters < float(self.constants.WEIGHT_PROOF_THRESHOLD):
            self.log.error(f"bad avg challenge block positioning ration: {avg_slot_iters / avg_ip_iters}")
            return False

        return True

    def _get_current_vars(self, idx, summaries):

        curr_difficulty = self.constants.DIFFICULTY_STARTING
        curr_ssi = self.constants.SUB_SLOT_ITERS_STARTING

        for ses in reversed(summaries[0:idx]):
            if ses.new_sub_slot_iters is not None:
                curr_ssi = ses.new_sub_slot_iters
                curr_difficulty = ses.new_difficulty
                break

        return curr_difficulty, curr_ssi

    def __get_rc_sub_slot_hash(
        self,
        segment: SubEpochChallengeSegment,
        summaries: List[SubEpochSummary],
    ) -> RewardChainSubSlot:

        ses = summaries[uint32(segment.sub_epoch_n - 1)]
        first_slot = segment.sub_slots[0]
        icc_sub_slot_hash: Optional[bytes32] = None
        if first_slot.icc_slot_end_info is not None:
            icc_sub_slot_hash = InfusedChallengeChainSubSlot(first_slot.icc_slot_end_info).get_hash()
        assert first_slot.cc_slot_end_info is not None

        cc_sub_slot = ChallengeChainSubSlot(
            first_slot.cc_slot_end_info,
            icc_sub_slot_hash,
            ses.get_hash(),
            ses.new_sub_slot_iters,
            ses.new_difficulty,
        )
        deficit: uint8 = self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
        if summaries[uint32(segment.sub_epoch_n)].num_sub_blocks_overflow == 0:
            deficit = uint8(deficit - 1)  # no overflow in start of sub epoch

        assert first_slot.rc_slot_end_info is not None
        rc_sub_slot = RewardChainSubSlot(
            first_slot.rc_slot_end_info,
            cc_sub_slot.get_hash(),
            icc_sub_slot_hash,
            uint8(deficit),  # -1 if no overflows in start of sub_epoch
        )
        return rc_sub_slot

    async def __create_sub_epoch_segments(
        self, ses_block: SubBlockRecord, se_start: SubBlockRecord, sub_epoch_n: uint32
    ) -> Optional[List[SubEpochChallengeSegment]]:

        # get headers in cache
        await self.block_cache.init_headers(uint32(se_start.sub_block_height), uint32(ses_block.sub_block_height + 30))
        segments: List[SubEpochChallengeSegment] = []

        curr: Optional[SubBlockRecord] = se_start
        height = se_start.sub_block_height
        assert curr is not None
        while curr.sub_block_height < ses_block.sub_block_height:
            if curr.is_challenge_sub_block(self.constants):
                self.log.debug(f"challenge segment, starts at {curr.sub_block_height} ")
                seg, height = await self._handle_challenge_segment(curr, sub_epoch_n)
                if seg is None:
                    self.log.error(f"failed creating segment {curr.header_hash} ")
                    return None
                segments.append(seg)
            else:
                height = height + uint32(1)  # type: ignore
            curr = self.block_cache.height_to_sub_block_record(height)
            if curr is None:
                return None
        self.log.info(f"next sub epoch starts at {height}")
        return segments

    async def _handle_challenge_segment(
        self, block_rec: SubBlockRecord, sub_epoch_n: uint32
    ) -> Tuple[Optional[SubEpochChallengeSegment], uint32]:
        assert self.block_cache is not None
        sub_slots: List[SubSlotData] = []
        self.log.debug(
            f"create challenge segment for block {block_rec.header_hash} sub_block_height {block_rec.sub_block_height} "
        )
        block_header = await self.block_cache.header_block(block_rec.header_hash)
        if block_header is None:
            return None, uint32(0)

        # VDFs from sub slots before challenge block
        first_sub_slots = await self.__first_sub_slots_data(block_header)
        if first_sub_slots is None:
            self.log.error("failed building first sub slots")
            return None, uint32(0)

        sub_slots.extend(first_sub_slots)

        # # VDFs from slot after challenge block to end of slot
        self.log.debug(
            f"create slot end vdf for block {block_header.header_hash} height {block_header.sub_block_height} "
        )

        challenge_slot_end_sub_slots, end_height = await self.__get_slot_end_vdf(block_header.sub_block_height + 1)
        if challenge_slot_end_sub_slots is None:
            self.log.error("failed building slot end ")
            return None, uint32(0)
        sub_slots.extend(challenge_slot_end_sub_slots)
        return (
            SubEpochChallengeSegment(sub_epoch_n, sub_slots),
            end_height,
        )

    async def __get_slot_end_vdf(self, start_height: uint32) -> Tuple[Optional[List[SubSlotData]], uint32]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        self.log.debug(f"slot end vdf start height {start_height}")
        curr = self.block_cache.height_to_sub_block_record(start_height)
        if curr is None:
            return None, uint32(0)
        curr_header = await self.block_cache.header_block(curr.header_hash)
        if curr_header is None:
            return None, uint32(0)
        cc_proofs: List[VDFProof] = []
        icc_proofs: List[VDFProof] = []
        sub_slots_data: List[SubSlotData] = []
        while not curr.is_challenge_sub_block(self.constants):
            for sub_slot in curr_header.finished_sub_slots:
                sub_slots_data.append(handle_finished_slots(sub_slot))
            # append sub slot proofs
            if curr_header.infused_challenge_chain_ip_proof is not None:
                icc_proofs.append(curr_header.infused_challenge_chain_ip_proof)
            if curr_header.challenge_chain_sp_proof is not None:
                cc_proofs.append(curr_header.challenge_chain_sp_proof)
            if curr_header.challenge_chain_ip_proof is not None:
                cc_proofs.append(curr_header.challenge_chain_ip_proof)
            curr = self.block_cache.height_to_sub_block_record(uint32(curr.sub_block_height + 1))
            if curr is None:
                return None, uint32(0)
            curr_header = await self.block_cache.header_block(curr.header_hash)
            if curr_header is None:
                return None, uint32(0)
        self.log.debug(f"slot end vdf end height {curr.sub_block_height}")
        return sub_slots_data, curr.sub_block_height

    # returns a challenge chain vdf from slot start to signage point
    async def __first_sub_slots_data(self, block: HeaderBlock) -> Optional[List[SubSlotData]]:
        # combine cc vdfs of all reward blocks from the start of the sub slot to end

        curr: Optional[HeaderBlock] = block
        # find slot start
        assert curr is not None
        while not curr.first_in_sub_slot and curr.sub_block_height > 0:
            curr = await self.block_cache.header_block(curr.prev_header_hash)
            if curr is None:
                return None

        # get all finished sub slots
        sub_slots: List[SubSlotData] = []
        for sub_slot in curr.finished_sub_slots:
            sub_slots.append(handle_finished_slots(sub_slot))

        cc_slot_end_vdf: List[VDFProof] = []
        icc_slot_end_vdf: List[VDFProof] = []
        while curr.sub_block_height < block.sub_block_height:
            curr = await self.block_cache.height_to_header_block(curr.sub_block_height + 1)
            if curr is None:
                return None

            if curr.challenge_chain_sp_proof is not None:
                cc_slot_end_vdf.append(curr.challenge_chain_sp_proof)
            if curr.challenge_chain_sp_proof is not None:
                cc_slot_end_vdf.append(curr.challenge_chain_ip_proof)
            if curr.infused_challenge_chain_ip_proof is not None:
                icc_slot_end_vdf.append(curr.infused_challenge_chain_ip_proof)

        # sub_slots.append(handle_finished_slots(cc_slot_end_vdf, curr, icc_slot_end_vdf))
        self.log.debug(f"add challenge block height {block.sub_block_height}")
        ssd = SubSlotData(
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
        sub_slots.append(ssd)
        return sub_slots

    def __validate_pospace(
        self,
        segment: SubEpochChallengeSegment,
        idx: int,
        curr_diff: uint64,
        prev_cc_sub_slot: Optional[bytes32],
    ) -> Optional[uint64]:

        # find challenge block sub slot
        challenge_sub_slot: SubSlotData = segment.sub_slots[idx]

        if prev_cc_sub_slot is None:
            # genesis
            cc_sp_hash: bytes32 = self.constants.FIRST_CC_CHALLENGE
            challenge = self.constants.FIRST_CC_CHALLENGE
        else:
            challenge = prev_cc_sub_slot
            if challenge_sub_slot.cc_sp_vdf_info is None:
                cc_sp_hash = prev_cc_sub_slot
            else:
                cc_sp_hash = challenge_sub_slot.cc_sp_vdf_info.output.get_hash()

        # validate proof of space
        assert challenge_sub_slot.proof_of_space is not None
        q_str = challenge_sub_slot.proof_of_space.verify_and_get_quality_string(
            self.constants,
            challenge,
            cc_sp_hash,
        )
        if q_str is None:
            self.log.error("could not verify proof of space")
            return None
        return calculate_iterations_quality(
            q_str,
            challenge_sub_slot.proof_of_space.size,
            curr_diff,
            cc_sp_hash,
        )

    def get_cc_sub_slot_hash(self, prev_sub_slot: Optional[SubSlotData], ses: Optional[SubEpochSummary]):
        if prev_sub_slot is None:
            # genesis
            return self.constants.FIRST_CC_CHALLENGE
        cc_vdf = prev_sub_slot.cc_slot_end_info
        icc_vdf = prev_sub_slot.icc_slot_end_info
        icc_vdf_hash: Optional[bytes32] = None
        if icc_vdf is not None:
            icc_vdf_hash = icc_vdf.get_hash()
        assert cc_vdf is not None
        cc_sub_slot = ChallengeChainSubSlot(
            cc_vdf,
            icc_vdf_hash,
            None if ses is None else ses.get_hash(),
            None if ses is None else ses.new_sub_slot_iters,
            None if ses is None else ses.new_difficulty,
        )
        return cc_sub_slot.get_hash()

    def _validate_segment_slots(
        self,
        segment: SubEpochChallengeSegment,
        curr_ssi: uint64,
        curr_difficulty: uint64,
        ses: Optional[SubEpochSummary],
        prev_ssd: Optional[SubSlotData],
    ) -> Tuple[bool, int, int, int, int]:
        ip_iters, slot_iters, slots, challenge_blocks = 0, 0, 0, 0
        for idx, sub_slot_data in enumerate(segment.sub_slots):
            slot_iters = slot_iters + curr_ssi  # type: ignore
            slots = slots + uint64(1)  # type: ignore

            if sub_slot_data.is_challenge():
                cc_sub_slot_hash = self.get_cc_sub_slot_hash(prev_ssd, ses)
                required_iters = self.__validate_pospace(segment, idx, curr_difficulty, cc_sub_slot_hash)
                if required_iters is None:
                    return False, uint64(0), uint64(0), uint64(0), 0
                assert sub_slot_data.cc_signage_point_index is not None
                ip_iters = ip_iters + calculate_ip_iters(  # type: ignore
                    self.constants, curr_ssi, sub_slot_data.cc_signage_point_index, required_iters
                )
                challenge_blocks = challenge_blocks + 1

            # if not validate_sub_slot_vdfs(self.constants, sub_slot_data, prev_ssd):
            #    self.log.info(f"failed to validate {idx} sub slot vdfs")
            # return False, uint64(0), uint64(0), uint64(0), uint64(0)

            prev_ssd = sub_slot_data
        return True, ip_iters, slot_iters, slots, challenge_blocks

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

    def _get_weights_for_sampling(
        self, rng: random.Random, total_weight: uint128, recent_chain: List[ProofBlockHeader]
    ) -> Optional[List[uint128]]:
        weight_to_check = []
        last_l_weight = recent_chain[-1].reward_chain_sub_block.weight - recent_chain[0].reward_chain_sub_block.weight
        delta = last_l_weight / total_weight
        prob_of_adv_succeeding = 1 - math.log(self.C, delta)
        if prob_of_adv_succeeding <= 0:
            self.log.warning(f"sample prob: {prob_of_adv_succeeding}")
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


def _make_sub_epoch_data(
    sub_epoch_summary: SubEpochSummary,
) -> SubEpochData:
    reward_chain_hash: bytes32 = sub_epoch_summary.reward_chain_hash
    #  Number of subblocks overflow in previous slot
    previous_sub_epoch_overflows: uint8 = sub_epoch_summary.num_sub_blocks_overflow  # total in sub epoch - expected
    #  New work difficulty and iterations per sub-slot
    sub_slot_iters: Optional[uint64] = sub_epoch_summary.new_sub_slot_iters
    new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty
    return SubEpochData(reward_chain_hash, previous_sub_epoch_overflows, sub_slot_iters, new_difficulty)


def validate_sub_slot_vdfs(constants: ConsensusConstants, sub_slot: SubSlotData, prev_sub_slot: SubSlotData) -> bool:
    default = ClassgroupElement.get_default_element()
    if sub_slot.is_challenge():
        assert prev_sub_slot.cc_sp_vdf_info is not None
        assert sub_slot.cc_signage_point is not None
        if not sub_slot.cc_signage_point.is_valid(constants, default, prev_sub_slot.cc_sp_vdf_info):
            return False
        assert sub_slot.cc_infusion_point is not None
        assert prev_sub_slot.cc_slot_end_info is not None
        if not sub_slot.cc_infusion_point.is_valid(constants, default, prev_sub_slot.cc_slot_end_info):
            return False
        assert prev_sub_slot.icc_slot_end_info is not None
        assert sub_slot.icc_slot_end is not None
        if not sub_slot.icc_slot_end.is_valid(constants, default, prev_sub_slot.icc_slot_end_info):
            return False
        return True
    assert sub_slot.cc_slot_end is not None
    assert sub_slot.cc_slot_end_info is not None
    return sub_slot.cc_slot_end.is_valid(constants, default, sub_slot.cc_slot_end_info)


def _map_summaries(
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

        if idx < len(sub_epoch_data) - 1:
            delta = 0
            if idx > 0:
                delta = sub_epoch_data[idx].num_sub_blocks_overflow
            sub_epoch_data_weight = sub_epoch_data_weight + uint128(  # type: ignore
                curr_difficulty * (sub_blocks_for_se + sub_epoch_data[idx + 1].num_sub_blocks_overflow - delta)
            )
        # if new epoch update diff and iters
        if data.new_difficulty is not None:
            curr_difficulty = data.new_difficulty

        # add to dict
        summaries.append(ses)
        ses_hash = std_hash(ses)
    return summaries, sub_epoch_data_weight


def _get_last_ses_block_idx(
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


def handle_finished_slots(end_of_slot: EndOfSubSlotBundle):
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
