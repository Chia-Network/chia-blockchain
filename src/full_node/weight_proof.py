import asyncio
import logging
import random
from typing import Optional, List, Tuple, Dict

import math

from src.consensus.blockchain_interface import BlockchainInterface
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_iterations_quality, calculate_ip_iters
from src.consensus.block_record import BlockRecord
from src.types.blockchain_format.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.header_block import HeaderBlock
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot, InfusedChallengeChainSubSlot
from src.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from src.types.blockchain_format.vdf import VDFProof, VDFInfo
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
        blockchain: BlockchainInterface,
        name: str = None,
    ):
        self.tip: Optional[bytes32] = None
        self.proof: Optional[WeightProof] = None
        self.constants = constants
        self.blockchain = blockchain
        self.lock = asyncio.Lock()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(self.WeightProofHandler)

    async def get_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:

        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            self.log.error("unknown tip")
            return None

        if tip_rec.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            self.log.debug("chain to short for weight proof")
            return None

        await self.lock.acquire()
        if self.proof is not None:
            if tip == self.tip:
                self.lock.release()
                return self.proof
            new_wp = await self._extend_proof_of_weight(self.proof, tip_rec)
            if new_wp is None or not self._validate_sub_epoch_summaries(new_wp):
                self.log.error("weight proof failed pre send validation")
                self.log.debug("---------------extended wp--------------------")
                self.log.debug(f" \n {new_wp}")
                wp = await self._create_proof_of_weight(tip)
                self.log.debug("-----------------new wp--------------------")
                self.log.debug(f" \n {wp}")
                self.lock.release()
                return wp
            self.proof = new_wp
            self.tip = tip
            self.lock.release()
            return new_wp

        wp = await self._create_proof_of_weight(tip)
        if wp is None or not self._validate_sub_epoch_summaries(wp):
            self.log.error("weight proof failed pre send validation")
            self.lock.release()
            return None
        self.proof = wp
        self.tip = tip
        self.lock.release()
        return wp

    async def _extend_proof_of_weight(self, weight_proof: WeightProof, new_tip: BlockRecord) -> Optional[WeightProof]:
        # replace recent chain

        self.log.debug(f"extend weight proof peak {new_tip.header_hash} {new_tip.height}")

        recent_chain = await self._get_recent_chain(new_tip.height, weight_proof)
        if recent_chain is None:
            return None
        end_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        sub_epoch_data = weight_proof.sub_epochs
        heights = self.blockchain.get_ses_heights()
        for height in heights:
            if height <= end_height:
                continue
            if height > new_tip.height:
                break
            summary = self.blockchain.get_ses(height)
            sub_epoch_data.append(_make_sub_epoch_data(summary))

        # todo handle new sampling
        return WeightProof(sub_epoch_data, weight_proof.sub_epoch_segments, recent_chain)

    async def _create_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        """
        Creates a weight proof object
        """
        assert self.blockchain is not None
        sub_epoch_data: List[SubEpochData] = []
        sub_epoch_segments: List[SubEpochChallengeSegment] = []
        tip_rec = self.blockchain.block_record(tip)
        if tip_rec is None:
            self.log.error("failed not tip in cache")
            return None
        self.log.debug(f"create weight proof peak {tip} {tip_rec.height}")
        recent_chain = await self._get_recent_chain(tip_rec.height)
        if recent_chain is None:
            return None

        weight_to_check = self._get_weights_for_sampling(random.Random(tip), tip_rec.weight, recent_chain)
        if weight_to_check is None:
            self.log.warning("math error while sampling sub epochs")

        prev_ses_block = await self.blockchain.get_block_record_from_db(self.blockchain.height_to_hash(uint32(0)))
        if prev_ses_block is None:
            return None

        sub_epoch_n = uint32(0)
        summary_heights = self.blockchain.get_ses_heights()
        for idx, ses_height in enumerate(summary_heights):
            if ses_height > tip_rec.height:
                break
            # next block
            ses_block = await self.blockchain.get_block_record_from_db(self.blockchain.height_to_hash(ses_height))
            if ses_block is None or ses_block.sub_epoch_summary_included is None:
                self.log.error("error while building proof")
                return None

            self.log.debug(f"handle sub epoch summary {idx} at height: {ses_height} weight: {ses_block.weight}")
            sub_epoch_data.append(_make_sub_epoch_data(ses_block.sub_epoch_summary_included))

            # if we have enough sub_epoch samples, dont sample
            if sub_epoch_n >= self.MAX_SAMPLES:
                self.log.debug("reached sampled sub epoch cap")
                continue

            # sample sub epoch
            if self._sample_sub_epoch(prev_ses_block, ses_block, weight_to_check):  # type: ignore
                segments = await self.blockchain.get_sub_epoch_challenge_segments(ses_block.height)
                if segments is None:
                    segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(idx))
                    if segments is None:
                        self.log.error(f"failed while building segments for sub epoch {idx}, ses height {ses_height} ")
                        return None
                    await self.blockchain.persist_sub_epoch_challenge_segments(ses_block.height, segments)
                self.log.debug(f"sub epoch {sub_epoch_n} has {len(segments)} segments")
                sub_epoch_segments.extend(segments)
                sub_epoch_n = uint32(sub_epoch_n + 1)
            prev_ses_block = ses_block
        self.log.debug(f"sub_epochs: {len(sub_epoch_data)}")
        return WeightProof(sub_epoch_data, sub_epoch_segments, recent_chain)

    def _sample_sub_epoch(
        self, start_of_epoch: BlockRecord, end_of_epoch: BlockRecord, weight_to_check: List[uint128]
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
                if block.reward_chain_block.height == curr_height:
                    break
                idx += 1

            if idx < len(wp.recent_chain_data):
                for block in wp.recent_chain_data[idx:]:
                    recent_chain.append(block)
                    assert curr_height == block.reward_chain_block.height
                    curr_height = curr_height + uint32(1)  # type: ignore
                    idx += 1

        headers: Dict[bytes32, HeaderBlock] = await self.blockchain.get_header_blocks_in_range(curr_height, tip_height)
        while curr_height <= tip_height:
            # add to needed reward chain recent blocks
            header_block = headers[self.blockchain.height_to_hash(curr_height)]
            if header_block is None:
                self.log.error("creating recent chain failed")
                return None
            recent_chain.append(ProofBlockHeader(header_block.finished_sub_slots, header_block.reward_chain_block))
            curr_height = curr_height + uint32(1)  # type: ignore

        self.log.debug(
            f"recent chain, "
            f"start: {recent_chain[0].reward_chain_block.height} "
            f"end:  {recent_chain[-1].reward_chain_block.height} "
        )
        return recent_chain

    def validate_weight_proof(self, weight_proof: WeightProof) -> Tuple[bool, uint32]:
        # sub epoch summaries validate hashes
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)

        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        self.log.debug(f"validate weight proof peak height {peak_height}")
        summaries = self._validate_sub_epoch_summaries(weight_proof)
        if summaries is None:
            self.log.warning("weight proof failed sub epoch data validation")
            return False, uint32(0)

        self.log.debug("validate sub epoch challenge segments")
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
        assert self.blockchain is not None

        last_ses_hash, last_ses_height = _get_last_ses_hash(self.constants, weight_proof.recent_chain_data)
        if last_ses_hash is None:
            self.log.warning("could not find last ses block")
            return None

        summaries, sub_epoch_data_weight = _map_summaries(
            self.constants.SUB_EPOCH_BLOCKS,
            self.constants.GENESIS_CHALLENGE,
            weight_proof.sub_epochs,
            self.constants.DIFFICULTY_STARTING,
        )

        self.log.debug(f"validating {len(summaries)} summaries")

        # validate weight
        if not self._validate_summaries_weight(sub_epoch_data_weight, summaries, weight_proof):
            self.log.error("failed validating weight")
            return None

        last_ses = summaries[-1]
        self.log.debug(f"last ses height {last_ses_height}")
        # validate last ses_hash
        if last_ses.get_hash() != last_ses_hash:
            self.log.error(f"failed to validate ses hashes block height {last_ses_height}")
            return None
        return summaries

    def _validate_summaries_weight(self, sub_epoch_data_weight, summaries, weight_proof) -> bool:
        num_over = summaries[-1].num_blocks_overflow
        ses_end_height = (len(summaries) - 1) * self.constants.SUB_EPOCH_BLOCKS + num_over - 1
        curr = None
        for block in weight_proof.recent_chain_data:
            if block.reward_chain_block.height == ses_end_height:
                curr = block
        if curr is None:
            return False

        return curr.reward_chain_block.weight == sub_epoch_data_weight

    def _validate_segments(
        self,
        weight_proof: WeightProof,
        summaries: List[SubEpochSummary],
    ):
        rc_sub_slot_hash = self.constants.GENESIS_CHALLENGE
        curr_difficulty = self.constants.DIFFICULTY_STARTING
        curr_ssi = self.constants.SUB_SLOT_ITERS_STARTING
        total_blocks, total_ip_iters = 0, 0
        total_slot_iters, total_slots = 0, 0
        total_ip_iters = 0
        curr_sub_epoch_n = -1
        prev_ses: Optional[SubEpochSummary] = None
        for idx, segment in enumerate(weight_proof.sub_epoch_segments):
            if curr_sub_epoch_n < segment.sub_epoch_n:
                self.log.debug(f"handle sub epoch {segment.sub_epoch_n}")
                # recreate RewardChainSubSlot for next ses rc_hash
                if segment.sub_epoch_n > 0:
                    rc_sub_slot_hash = self.__get_rc_sub_slot_hash(segment, summaries).get_hash()
                    prev_ses = summaries[segment.sub_epoch_n - 1]
                    curr_difficulty, curr_ssi = self._get_current_vars(segment.sub_epoch_n, summaries)

                if not summaries[segment.sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
                    self.log.error(f"failed reward_chain_hash validation sub_epoch {segment.sub_epoch_n}")
                    return False

            valid_segment, ip_iters, slot_iters, slots, blocks = self._validate_segment_slots(
                segment,
                curr_ssi,
                curr_difficulty,
                prev_ses,
            )
            prev_ses = None
            if not valid_segment:
                self.log.error(f"failed to validate sub_epoch {segment.sub_epoch_n} slots")
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
        slot_idx = -1
        for idx, curr in enumerate(segment.sub_slots):
            if curr.is_challenge():
                slot_idx = idx - 1
                break

        assert slot_idx > -1
        first_slot = segment.sub_slots[slot_idx]
        icc_sub_slot_hash: Optional[bytes32] = None
        if first_slot.icc_slot_end_info is not None:
            icc_sub_slot_hash = InfusedChallengeChainSubSlot(first_slot.icc_slot_end_info).get_hash()
        assert first_slot.cc_slot_end_info is not None

        cc_sub_slot = ChallengeChainSubSlot(
            first_slot.cc_slot_end_info,
            icc_sub_slot_hash,
            None if slot_idx != 0 else ses.get_hash(),
            None if slot_idx != 0 else ses.new_sub_slot_iters,
            None if slot_idx != 0 else ses.new_difficulty,
        )
        # self.log.debug(f"cc sub slot {cc_sub_slot}    \n {cc_sub_slot.get_hash()}")

        assert first_slot.rc_slot_end_info is not None
        rc_sub_slot = RewardChainSubSlot(
            first_slot.rc_slot_end_info,
            cc_sub_slot.get_hash(),
            icc_sub_slot_hash,
            self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK,
        )
        # self.log.debug(f"rc sub slot {rc_sub_slot}    \n {rc_sub_slot.get_hash()}")
        return rc_sub_slot

    async def create_prev_sub_epoch_segments(self):
        self.log.debug("create prev sub_epoch_segments")
        heights = self.blockchain.get_ses_heights()
        if len(heights) < 3:
            return
        count = len(heights) - 2
        ses_block = self.blockchain.height_to_block_record(heights[-2])
        prev_ses_block = self.blockchain.height_to_block_record(heights[-3])
        assert prev_ses_block.sub_epoch_summary_included is not None
        segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(count))
        assert segments is not None
        await self.blockchain.persist_sub_epoch_challenge_segments(ses_block.height, segments)
        self.log.debug("sub_epoch_segments done")
        return

    async def __create_sub_epoch_segments(
        self, ses_block: BlockRecord, se_start: BlockRecord, sub_epoch_n: uint32
    ) -> Optional[List[SubEpochChallengeSegment]]:
        segments: List[SubEpochChallengeSegment] = []
        blocks = await self.blockchain.get_block_records_in_range(
            se_start.height, ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS
        )
        header_blocks = await self.blockchain.get_header_blocks_in_range(
            se_start.height, ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS
        )
        curr: Optional[HeaderBlock] = header_blocks[se_start.header_hash]
        height = se_start.height
        assert curr is not None
        while curr.height < ses_block.height:
            if blocks[curr.header_hash].is_challenge_block(self.constants):
                self.log.debug(f"challenge segment, starts at {curr.height} ")
                seg, height = await self._handle_challenge_segment(curr, sub_epoch_n, header_blocks, blocks)
                if seg is None:
                    self.log.error(f"failed creating segment {curr.header_hash} ")
                    return None
                segments.append(seg)
            else:
                height = height + uint32(1)  # type: ignore
            curr = header_blocks[self.blockchain.height_to_hash(height)]
            if curr is None:
                return None
        self.log.debug(f"next sub epoch starts at {height}")
        return segments

    async def _handle_challenge_segment(
        self,
        header_block: HeaderBlock,
        sub_epoch_n: uint32,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
    ) -> Tuple[Optional[SubEpochChallengeSegment], uint32]:
        assert self.blockchain is not None
        sub_slots: List[SubSlotData] = []
        self.log.debug(
            f"create challenge segment for block {header_block.header_hash}" f" height {header_block.height} "
        )

        # VDFs from sub slots before challenge block
        first_sub_slots = await self.__first_sub_slots_data(header_block, header_blocks)
        if first_sub_slots is None:
            self.log.error("failed building first sub slots")
            return None, uint32(0)

        sub_slots.extend(first_sub_slots)

        # # VDFs from slot after challenge block to end of slot
        self.log.debug(f"create slot end vdf for block {header_block.header_hash} height {header_block.height} ")

        challenge_slot_end_sub_slots, end_height = await self.__get_slot_end_vdf(
            uint32(header_block.height + 1), header_blocks, blocks
        )
        if challenge_slot_end_sub_slots is None:
            self.log.error("failed building slot end ")
            return None, uint32(0)
        sub_slots.extend(challenge_slot_end_sub_slots)
        return (
            SubEpochChallengeSegment(sub_epoch_n, sub_slots),
            end_height,
        )

    async def __get_slot_end_vdf(
        self, start_height: uint32, header_blocks: Dict[bytes32, HeaderBlock], blocks: Dict[bytes32, BlockRecord]
    ) -> Tuple[Optional[List[SubSlotData]], uint32]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        self.log.debug(f"slot end vdf start height {start_height}")
        curr = header_blocks[self.blockchain.height_to_hash(start_height)]
        cc_proofs: List[VDFProof] = []
        icc_proofs: List[VDFProof] = []
        sub_slots_data: List[SubSlotData] = []
        while not blocks[curr.header_hash].is_challenge_block(self.constants):
            for sub_slot in curr.finished_sub_slots:
                sub_slots_data.append(handle_finished_slots(sub_slot))
            # append sub slot proofs
            if curr.infused_challenge_chain_ip_proof is not None:
                icc_proofs.append(curr.infused_challenge_chain_ip_proof)
            if curr.challenge_chain_sp_proof is not None:
                cc_proofs.append(curr.challenge_chain_sp_proof)
            if curr.challenge_chain_ip_proof is not None:
                cc_proofs.append(curr.challenge_chain_ip_proof)
            curr = header_blocks[self.blockchain.height_to_hash(uint32(curr.height + 1))]
        self.log.debug(f"slot end vdf end height {curr.height}")
        return sub_slots_data, curr.height

    # returns a challenge chain vdf from slot start to signage point
    async def __first_sub_slots_data(
        self,
        header_block: HeaderBlock,
        header_blocks: Dict[bytes32, HeaderBlock],
    ) -> Optional[List[SubSlotData]]:
        # combine cc vdfs of all reward blocks from the start of the sub slot to end

        curr_header = header_block
        # find slot start
        while not curr_header.first_in_sub_slot and curr_header.height > 0:
            curr_header = header_blocks[curr_header.prev_hash]

        # get all finished sub slots
        sub_slots: List[SubSlotData] = []
        for sub_slot in curr_header.finished_sub_slots:
            sub_slots.append(handle_finished_slots(sub_slot))

        cc_slot_end_vdf: List[VDFProof] = []
        icc_slot_end_vdf: List[VDFProof] = []
        curr_header = header_blocks[curr_header.header_hash]
        while curr_header.height < header_block.height:
            curr_header = header_blocks[self.blockchain.height_to_hash(uint32(curr_header.height + 1))]
            if curr_header is None:
                return None

            if curr_header.challenge_chain_sp_proof is not None:
                cc_slot_end_vdf.append(curr_header.challenge_chain_sp_proof)
            if curr_header.challenge_chain_sp_proof is not None:
                cc_slot_end_vdf.append(curr_header.challenge_chain_ip_proof)
            if curr_header.infused_challenge_chain_ip_proof is not None:
                icc_slot_end_vdf.append(curr_header.infused_challenge_chain_ip_proof)

        self.log.debug(f"add challenge block height {header_block.height}")
        ssd = SubSlotData(
            header_block.reward_chain_block.proof_of_space,
            header_block.reward_chain_block.challenge_chain_sp_signature,
            header_block.challenge_chain_sp_proof,
            header_block.challenge_chain_ip_proof,
            header_block.reward_chain_block.challenge_chain_sp_vdf,
            header_block.reward_chain_block.signage_point_index,
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
            cc_sp_hash: bytes32 = self.constants.GENESIS_CHALLENGE
            challenge = self.constants.GENESIS_CHALLENGE
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
            self.constants.DIFFICULTY_CONSTANT_FACTOR,
            q_str,
            challenge_sub_slot.proof_of_space.size,
            curr_diff,
            cc_sp_hash,
        )

    def get_cc_sub_slot_hash(self, segment: SubEpochChallengeSegment, idx, ses: Optional[SubEpochSummary]):
        if segment.sub_epoch_n == 0 and idx == 0:
            # genesis
            return self.constants.GENESIS_CHALLENGE
        prev_sub_slot = segment.sub_slots[idx - 1]
        cc_vdf = prev_sub_slot.cc_slot_end_info
        icc_vdf = prev_sub_slot.icc_slot_end_info
        icc_vdf_hash: Optional[bytes32] = None
        if icc_vdf is not None:
            icc_vdf_hash = icc_vdf.get_hash()
        assert cc_vdf is not None
        cc_sub_slot = ChallengeChainSubSlot(
            cc_vdf,
            icc_vdf_hash,
            None if idx > 1 or ses is None else ses.get_hash(),
            None if idx > 1 or ses is None else ses.new_sub_slot_iters,
            None if idx > 1 or ses is None else ses.new_difficulty,
        )

        return cc_sub_slot.get_hash()

    def _validate_segment_slots(
        self,
        segment: SubEpochChallengeSegment,
        curr_ssi: uint64,
        curr_difficulty: uint64,
        ses: Optional[SubEpochSummary],
    ) -> Tuple[bool, int, int, int, int]:
        ip_iters, slot_iters, slots, challenge_blocks = 0, 0, 0, 0
        for idx, sub_slot_data in enumerate(segment.sub_slots):
            slot_iters = slot_iters + curr_ssi  # type: ignore
            slots = slots + uint64(1)  # type: ignore
            if sub_slot_data.is_challenge():
                cc_sub_slot_hash = self.get_cc_sub_slot_hash(segment, idx, ses)
                required_iters = self.__validate_pospace(segment, idx, curr_difficulty, cc_sub_slot_hash)
                if required_iters is None:
                    return False, uint64(0), uint64(0), uint64(0), 0
                assert sub_slot_data.cc_signage_point_index is not None
                ip_iters = ip_iters + calculate_ip_iters(  # type: ignore
                    self.constants, curr_ssi, sub_slot_data.cc_signage_point_index, required_iters
                )
                challenge_blocks = challenge_blocks + 1

            # if not validate_sub_slot_vdfs(self.constants, sub_slot_data, prev_ssd):
            #    self.log.debug(f"failed to validate {idx} sub slot vdfs")
            # return False, uint64(0), uint64(0), uint64(0), uint64(0)

        return True, ip_iters, slot_iters, slots, challenge_blocks

    def get_fork_point(self, received_summaries: List[SubEpochSummary]) -> uint32:
        # iterate through sub epoch summaries to find fork point
        fork_point_index = 0
        ses_heights = self.blockchain.get_ses_heights()
        for idx, summary_height in enumerate(ses_heights):
            self.log.debug(f"check summary {idx} height {summary_height}")
            local_ses = self.blockchain.get_ses(summary_height)
            if local_ses is None or local_ses.get_hash() != received_summaries[idx].get_hash():
                break
            fork_point_index = idx

        if fork_point_index > 2:
            # Two summeries can have different blocks and still be identical
            # This gets resolved after one full sub epoch
            height = ses_heights[fork_point_index - 2]
        else:
            height = uint32(0)

        return height

    def _get_weights_for_sampling(
        self, rng: random.Random, total_weight: uint128, recent_chain: List[ProofBlockHeader]
    ) -> Optional[List[uint128]]:
        weight_to_check = []
        last_l_weight = recent_chain[-1].reward_chain_block.weight - recent_chain[0].reward_chain_block.weight
        delta = last_l_weight / total_weight
        prob_of_adv_succeeding = 1 - math.log(self.C, delta)
        if prob_of_adv_succeeding <= 0:
            self.log.debug(f"sample prob: {prob_of_adv_succeeding}")
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
    #  Number of blocks overflow in previous slot
    previous_sub_epoch_overflows: uint8 = sub_epoch_summary.num_blocks_overflow  # total in sub epoch - expected
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
    blocks_for_se: uint32,
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
            data.num_blocks_overflow,
            data.new_difficulty,
            data.new_sub_slot_iters,
        )

        if idx < len(sub_epoch_data) - 1:
            delta = 0
            if idx > 0:
                delta = sub_epoch_data[idx].num_blocks_overflow
            sub_epoch_data_weight = sub_epoch_data_weight + uint128(  # type: ignore
                curr_difficulty * (blocks_for_se + sub_epoch_data[idx + 1].num_blocks_overflow - delta)
            )
        # if new epoch update diff and iters
        if data.new_difficulty is not None:
            curr_difficulty = data.new_difficulty

        # add to dict
        summaries.append(ses)
        ses_hash = std_hash(ses)
    return summaries, sub_epoch_data_weight


def _get_last_ses_hash(
    constants: ConsensusConstants, recent_reward_chain: List[ProofBlockHeader]
) -> Tuple[Optional[bytes32], uint32]:
    for idx, block in enumerate(reversed(recent_reward_chain)):
        if (block.reward_chain_block.height % constants.SUB_EPOCH_BLOCKS) == 0:
            idx = len(recent_reward_chain) - 1 - idx  # reverse
            # find first block after sub slot end
            while idx < len(recent_reward_chain):
                curr = recent_reward_chain[idx]
                if len(curr.finished_sub_slots) > 0:
                    for slot in curr.finished_sub_slots:
                        if slot.challenge_chain.subepoch_summary_hash is not None:
                            return (
                                slot.challenge_chain.subepoch_summary_hash,
                                curr.reward_chain_block.height,
                            )
                idx += 1
    return None, uint32(0)


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
