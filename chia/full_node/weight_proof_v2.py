import asyncio
import dataclasses
import logging
import math
import random
import time
from concurrent.futures.process import ProcessPoolExecutor
from typing import Dict, List, Optional, Tuple

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import header_block_to_sub_block_record
from chia.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_sp_iters,
    is_overflow_block,
)
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info

from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import (
    SubEpochData,
    SubEpochSegmentsV2,
    RecentChainData,
)
from chia.types.weight_proof import WeightProofV2, SubEpochChallengeSegmentV2, SubSlotDataV2
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import dataclass_from_dict, recurse_jsonify

log = logging.getLogger(__name__)


class WeightProofHandlerV2:

    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 20

    def __init__(
        self,
        constants: ConsensusConstants,
        blockchain: BlockchainInterface,
    ):
        self.tip: Optional[bytes32] = None
        self.proof: Optional[WeightProofV2] = None
        self.constants = constants
        self.blockchain = blockchain
        self.lock = asyncio.Lock()

    async def get_proof_of_weight(self, tip: bytes32) -> Optional[WeightProofV2]:

        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            log.error("unknown tip")
            return None

        if tip_rec.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            log.debug("need at least 3 sub epochs for weight proof")
            return None

        async with self.lock:
            wp = await self._create_proof_of_weight(tip)
            if wp is None:
                return None
            self.proof = wp
            self.tip = tip
            return wp

    def validate_weight_proof_single_proc(self, weight_proof: WeightProofV2) -> Tuple[bool, uint32]:
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)

        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.warning("weight proof failed sub epoch data validation")
            return False, uint32(0)
        constants, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(
            self.constants, summaries, weight_proof
        )
        log.info("validate sub epoch challenge segments")
        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error("failed weight proof sub epoch sample validation")
            return False, uint32(0)

        if not _validate_sub_epoch_segments(constants, rng, wp_segment_bytes, summary_bytes):
            return False, uint32(0)
        log.info("validate weight proof recent blocks")
        if not _validate_recent_blocks(constants, wp_recent_chain_bytes, summary_bytes):
            return False, uint32(0)
        return True, self.get_fork_point(summaries)

    def get_fork_point_no_validations(self, weight_proof: WeightProofV2) -> Tuple[bool, uint32]:
        log.debug("get fork point skip validations")
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.warning("weight proof failed to validate sub epoch summaries")
            return False, uint32(0)
        return True, self.get_fork_point(summaries)

    async def validate_weight_proof(self, weight_proof: WeightProofV2) -> Tuple[bool, uint32, List[SubEpochSummary]]:
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0), []

        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")

        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.error("weight proof failed sub epoch data validation")
            return False, uint32(0), []

        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error("failed weight proof sub epoch sample validation")
            return False, uint32(0), []

        executor = ProcessPoolExecutor(1)
        constants, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(
            self.constants, summaries, weight_proof
        )
        segment_validation_task = asyncio.get_running_loop().run_in_executor(
            executor, _validate_sub_epoch_segments, constants, rng, wp_segment_bytes, summary_bytes
        )

        recent_blocks_validation_task = asyncio.get_running_loop().run_in_executor(
            executor, _validate_recent_blocks, constants, wp_recent_chain_bytes, summary_bytes
        )

        valid_segment_task = segment_validation_task
        valid_recent_blocks_task = recent_blocks_validation_task
        valid_recent_blocks = await valid_recent_blocks_task
        if not valid_recent_blocks:
            log.error("failed validating weight proof recent blocks")
            return False, uint32(0), []

        valid_segments = await valid_segment_task
        if not valid_segments:
            log.error("failed validating weight proof sub epoch segments")
            return False, uint32(0), []

        return True, self.get_fork_point(summaries), summaries

    def get_fork_point(self, received_summaries: List[SubEpochSummary]) -> uint32:
        # iterate through sub epoch summaries to find fork point
        fork_point_index = 0
        ses_heights = self.blockchain.get_ses_heights()
        for idx, summary_height in enumerate(ses_heights):
            log.debug(f"check summary {idx} height {summary_height}")
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

    async def get_sub_epoch_data(self, tip_height: uint32, summary_heights: List[uint32]) -> List[SubEpochData]:
        sub_epoch_data: List[SubEpochData] = []
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            if ses_height > tip_height:
                break
            ses = self.blockchain.get_ses(ses_height)
            log.debug(f"handle sub epoch summary {sub_epoch_n} at height: {ses_height}  ")
            sub_epoch_data.append(_create_sub_epoch_data(ses))
        return sub_epoch_data

    def get_seed_for_proof(self, summary_heights: List[uint32], tip_height) -> bytes32:
        count = 0
        ses = None
        for sub_epoch_n, ses_height in enumerate(reversed(summary_heights)):
            if ses_height <= tip_height:
                count += 1
            if count == 2:
                ses = self.blockchain.get_ses(ses_height)
                break
        assert ses is not None
        seed = ses.get_hash()
        return seed

    async def _create_proof_of_weight(self, tip: bytes32) -> Optional[WeightProofV2]:
        """
        Creates a weight proof object
        """
        start = time.time()
        assert self.blockchain is not None
        sub_epoch_segments: List[SubEpochChallengeSegmentV2] = []
        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            log.error("failed not tip in cache")
            return None
        log.info(f"create weight proof peak {tip} {tip_rec.height}")
        recent_chain = await self._get_recent_chain(tip_rec.height)
        if recent_chain is None:
            return None

        summary_heights = self.blockchain.get_ses_heights()
        sub_epoch_data = await self.get_sub_epoch_data(tip_rec.height, summary_heights)

        # use 2 last ses weight as last l weight
        seed = self.get_seed_for_proof(summary_heights, tip_rec.height)
        rng = random.Random(seed)
        last_ses_block, prev_prev_ses_block = await self.get_last_l_weight(summary_heights, tip_rec.height)
        if last_ses_block is None or prev_prev_ses_block is None:
            return None
        last_l_weight = last_ses_block.weight - prev_prev_ses_block.weight
        log.debug(f"total weight {last_ses_block.weight} prev weight {prev_prev_ses_block.weight}")
        weight_to_check = _get_weights_for_sampling(rng, last_ses_block.weight, last_l_weight)
        sample_n = 0
        ses_blocks = await self.blockchain.get_block_records_at(summary_heights)
        if ses_blocks is None:
            return None

        # set prev_ses to genesis
        prev_ses_block = await self.blockchain.get_block_record_from_db(self.blockchain.height_to_hash(uint32(0)))
        if prev_ses_block is None:
            return None
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            if ses_height > tip_rec.height:
                break

            # if we have enough sub_epoch samples, dont sample
            if sample_n >= self.MAX_SAMPLES:
                log.debug("reached sampled sub epoch cap")
                break
            # sample sub epoch
            # next sub block
            ses_block = ses_blocks[sub_epoch_n]
            if ses_block is None or ses_block.sub_epoch_summary_included is None:
                log.error("error while building proof")
                return None

            if _sample_sub_epoch(prev_ses_block.weight, ses_block.weight, weight_to_check):  # type: ignore
                sample_n += 1
                segments = await self.blockchain.get_sub_epoch_challenge_segments_v2(ses_block.header_hash)
                if segments is None:
                    segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(sub_epoch_n))
                    if segments is None:
                        log.error(
                            f"failed while building segments for sub epoch {sub_epoch_n}, ses height {ses_height} "
                        )
                        return None
                    await self.blockchain.persist_sub_epoch_challenge_segments_v2(ses_block.header_hash, segments)
                # remove proofs from unsampled
                sampled_seg_index = rng.choice(range(len(segments)))
                segments = compress_segments(sampled_seg_index, segments)
                log.debug(f"sub epoch {sub_epoch_n} has {len(segments)} segments")
                sub_epoch_segments.extend(segments)
            prev_ses_block = ses_block
        log.info(f"time to create proof: {time.time() - start}")
        return WeightProofV2(sub_epoch_data, sub_epoch_segments, recent_chain)

    async def get_last_l_weight(self, summary_heights, peak):
        summaries_n = len(summary_heights)
        for idx, height in enumerate(reversed(summary_heights)):
            if height <= peak:
                if summaries_n - idx < 3:
                    log.warning("chain to short not enough sub epochs ")
                    return None, None
                last_ses_block = await self.blockchain.get_block_record_from_db(
                    self.blockchain.height_to_hash(uint32(summary_heights[summaries_n - idx - 1]))
                )
                prev_prev_ses_block = await self.blockchain.get_block_record_from_db(
                    self.blockchain.height_to_hash(uint32(summary_heights[summaries_n - idx - 3]))
                )
                return last_ses_block, prev_prev_ses_block
        return None, None

    async def _get_recent_chain(self, tip_height: uint32) -> Optional[List[HeaderBlock]]:
        recent_chain: List[HeaderBlock] = []
        ses_heights = self.blockchain.get_ses_heights()
        min_height = 0
        count_ses = 0
        for ses_height in reversed(ses_heights):
            if ses_height <= tip_height:
                count_ses += 1
            if count_ses == 2:
                min_height = ses_height - 1
                break
        log.debug(f"start {min_height} end {tip_height}")
        headers = await self.blockchain.get_header_blocks_in_range(min_height, tip_height, tx_filter=False)
        blocks = await self.blockchain.get_block_records_in_range(min_height, tip_height)
        ses_count = 0
        curr_height = tip_height
        blocks_n = 0
        while ses_count < 2:
            if curr_height == 0:
                break
            # add to needed reward chain recent blocks
            header_block = headers[self.blockchain.height_to_hash(curr_height)]
            block_rec = blocks[header_block.header_hash]
            if header_block is None:
                log.error("creating recent chain failed")
                return None
            recent_chain.insert(0, header_block)
            if block_rec.sub_epoch_summary_included:
                ses_count += 1
            curr_height = uint32(curr_height - 1)  # type: ignore
            blocks_n += 1

        header_block = headers[self.blockchain.height_to_hash(curr_height)]
        recent_chain.insert(0, header_block)

        log.info(
            f"recent chain, "
            f"start: {recent_chain[0].reward_chain_block.height} "
            f"end:  {recent_chain[-1].reward_chain_block.height} "
        )
        return recent_chain

    async def create_sub_epoch_segments(self):
        log.debug("check segments in db")
        """
        Creates a weight proof object
         """
        assert self.blockchain is not None
        peak_height = self.blockchain.get_peak_height()
        if peak_height is None:
            log.error("no peak yet")
            return None

        summary_heights = self.blockchain.get_ses_heights()
        prev_ses_block = await self.blockchain.get_block_record_from_db(self.blockchain.height_to_hash(uint32(0)))
        if prev_ses_block is None:
            return None

        ses_blocks = await self.blockchain.get_block_records_at(summary_heights)
        if ses_blocks is None:
            return None

        for sub_epoch_n, ses_height in enumerate(summary_heights):
            log.debug(f"check db for sub epoch {sub_epoch_n}")
            if ses_height > peak_height:
                break
            ses_block = ses_blocks[sub_epoch_n]
            if ses_block is None or ses_block.sub_epoch_summary_included is None:
                log.error("error while building proof")
                return None
            await self.__create_persist_segment(prev_ses_block, ses_block, ses_height, sub_epoch_n)
            prev_ses_block = ses_block
            await asyncio.sleep(2)
        log.debug("done checking segments")
        return None

    async def __create_persist_segment(self, prev_ses_block, ses_block, ses_height, sub_epoch_n):
        segments = await self.blockchain.get_sub_epoch_challenge_segments_v2(ses_block.header_hash)
        if segments is None:
            segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(sub_epoch_n))
            if segments is None:
                log.error(f"failed while building segments for sub epoch {sub_epoch_n}, ses height {ses_height} ")
                return None
            await self.blockchain.persist_sub_epoch_challenge_segments_v2(ses_block.header_hash, segments)

    async def create_prev_sub_epoch_segments(self):
        log.debug("create prev sub_epoch_segments")
        heights = self.blockchain.get_ses_heights()
        if len(heights) < 3:
            return
        count = len(heights) - 2
        ses_sub_block = self.blockchain.height_to_block_record(heights[-2])
        prev_ses_sub_block = self.blockchain.height_to_block_record(heights[-3])
        assert prev_ses_sub_block.sub_epoch_summary_included is not None
        segments = await self.__create_sub_epoch_segments(ses_sub_block, prev_ses_sub_block, uint32(count))
        assert segments is not None
        await self.blockchain.persist_sub_epoch_challenge_segments_v2(ses_sub_block.header_hash, segments)
        log.debug("sub_epoch_segments done")
        return

    async def __create_sub_epoch_segments(
        self, ses_block: BlockRecord, se_start: BlockRecord, sub_epoch_n: uint32
    ) -> Optional[List[SubEpochChallengeSegmentV2]]:
        segments: List[SubEpochChallengeSegmentV2] = []
        start_height = await self.get_prev_two_slots_height(se_start)
        blocks = await self.blockchain.get_block_records_in_range(
            start_height, ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS
        )
        header_blocks = await self.blockchain.get_header_blocks_in_range(
            start_height, ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS, tx_filter=False
        )
        curr: Optional[HeaderBlock] = header_blocks[se_start.header_hash]
        height = se_start.height
        assert curr is not None
        first = True
        idx = 0
        while curr.height < ses_block.height:
            if blocks[curr.header_hash].is_challenge_block(self.constants):
                log.debug(f"challenge segment {idx}, starts at {curr.height} ")
                seg, height = await self._create_challenge_segment(curr, sub_epoch_n, header_blocks, blocks, first)
                if seg is None:
                    log.error(f"failed creating segment {curr.header_hash} ")
                    return None
                segments.append(seg)
                idx += 1
                first = False
            else:
                height = height + uint32(1)  # type: ignore
            curr = header_blocks[self.blockchain.height_to_hash(height)]
            if curr is None:
                return None
        log.debug(f"next sub epoch starts at {height}")
        return segments

    async def get_prev_two_slots_height(self, se_start: BlockRecord) -> uint32:
        # find prev 2 slots height
        slot = 0
        batch_size = 50
        curr_rec = se_start
        blocks = await self.blockchain.get_block_records_in_range(curr_rec.height - batch_size, curr_rec.height)
        end = curr_rec.height
        while slot < 2 and curr_rec.height > 0:
            if curr_rec.first_in_sub_slot:
                slot += 1
            if end - curr_rec.height == batch_size - 1:
                blocks = await self.blockchain.get_block_records_in_range(curr_rec.height - batch_size, curr_rec.height)
                end = curr_rec.height
            curr_rec = blocks[self.blockchain.height_to_hash(uint32(curr_rec.height - 1))]
        return curr_rec.height

    async def _create_challenge_segment(
        self,
        header_block: HeaderBlock,
        sub_epoch_n: uint32,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
        first_segment_in_sub_epoch: bool,
    ) -> Tuple[Optional[SubEpochChallengeSegmentV2], uint32]:
        assert self.blockchain is not None
        sub_slots: List[SubSlotDataV2] = []
        log.debug(f"create challenge segment block {header_block.header_hash} block height {header_block.height} ")
        # VDFs from sub slots before challenge block
        first_sub_slots, first_rc_end_of_slot_vdf, end_of_slot = await self.__first_sub_slot_vdfs(
            header_block, header_blocks, blocks, first_segment_in_sub_epoch
        )
        if first_sub_slots is None:
            log.error("failed building first sub slots")
            return None, uint32(0)

        sub_slots.extend(first_sub_slots)

        ssd = await _challenge_block_vdfs(
            self.constants,
            header_block,
            blocks[header_block.header_hash],
            blocks,
        )

        sub_slots.append(ssd)

        # # VDFs from slot after challenge block to end of slot
        log.debug(f"create slot end vdf for block {header_block.header_hash} height {header_block.height} ")

        challenge_slot_end_sub_slots, end_height = await self.__slot_end_vdf(
            uint32(header_block.height + 1), header_blocks, blocks
        )
        if challenge_slot_end_sub_slots is None:
            log.error("failed building slot end ")
            return None, uint32(0)
        sub_slots.extend(challenge_slot_end_sub_slots)
        if first_segment_in_sub_epoch and sub_epoch_n != 0:
            assert end_of_slot
            return (
                SubEpochChallengeSegmentV2(
                    sub_epoch_n,
                    sub_slots,
                    first_rc_end_of_slot_vdf,
                    end_of_slot.number_of_iterations,
                    end_of_slot.challenge,
                ),
                end_height,
            )
        return SubEpochChallengeSegmentV2(sub_epoch_n, sub_slots, None, None, None), end_height

    # returns a challenge chain vdf from slot start to signage point
    async def __first_sub_slot_vdfs(
        self,
        header_block: HeaderBlock,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
        first_in_sub_epoch: bool,
    ) -> Tuple[Optional[List[SubSlotDataV2]], Optional[VDFInfo], Optional[VDFInfo]]:
        # combine cc vdfs of all reward blocks from the start of the sub slot to end
        header_block_sub_rec = blocks[header_block.header_hash]
        # find slot start
        curr_sub_rec = header_block_sub_rec
        first_rc_end_of_slot_vdf = None
        end_of_slot_info = None

        while curr_sub_rec.height != 0 and blocks[curr_sub_rec.prev_hash].deficit != 0:
            curr_sub_rec = blocks[curr_sub_rec.prev_hash]

        if first_in_sub_epoch and curr_sub_rec.height > 0:
            if curr_sub_rec.sub_epoch_summary_included is None:
                log.error("expected sub epoch summary")
                return None, None, None
            first_rc_end_of_slot_vdf = (
                header_blocks[curr_sub_rec.header_hash].finished_sub_slots[-1].reward_chain.end_of_slot_vdf
            )
            end_of_slot_info = (
                header_blocks[curr_sub_rec.header_hash]
                .finished_sub_slots[-1]
                .challenge_chain.challenge_chain_end_of_slot_vdf
            )

        sub_slots_data: List[SubSlotDataV2] = []
        tmp_sub_slots_data: List[SubSlotDataV2] = []
        curr = header_blocks[curr_sub_rec.header_hash]
        log.debug(f"challenge starts at {curr.height}")
        curr = header_blocks[curr_sub_rec.header_hash]
        first = True
        while curr.height < header_block.height:
            if curr is None:
                log.error("failed fetching block")
                return None, None, None
            if curr.first_in_sub_slot and (first_in_sub_epoch or not first):
                # if not blue boxed
                if not blue_boxed_end_of_slot(curr.finished_sub_slots[0]):
                    sub_slots_data.extend(tmp_sub_slots_data)

                prev_rec = blocks[curr.prev_header_hash]
                for idx, sub_slot in enumerate(curr.finished_sub_slots):
                    sub_slots_data.append(handle_finished_slots(sub_slot, prev_rec.deficit))
                tmp_sub_slots_data = []
            sp_output = None
            if curr.reward_chain_block.challenge_chain_ip_vdf is not None:
                sp_output = curr.reward_chain_block.challenge_chain_ip_vdf.output
            ssd = SubSlotDataV2(
                None,
                None,
                None,
                curr.reward_chain_block.signage_point_index,
                None,
                sp_output,
                curr.reward_chain_block.challenge_chain_ip_vdf.output,
                None,
                None,
                None,
                curr.total_iters,
            )
            first = False
            tmp_sub_slots_data.append(ssd)
            curr = header_blocks[self.blockchain.height_to_hash(uint32(curr.height + 1))]

        if len(tmp_sub_slots_data) > 0:
            sub_slots_data.extend(tmp_sub_slots_data)

        deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
        if header_block.height > 0:
            deficit = blocks[header_block.prev_header_hash].deficit
        for idx, sub_slot in enumerate(header_block.finished_sub_slots):
            sub_slots_data.append(handle_finished_slots(sub_slot, deficit))

        return (sub_slots_data, first_rc_end_of_slot_vdf, end_of_slot_info)

    def first_rc_end_of_slot_vdf(
        self,
        header_block,
        blocks: Dict[bytes32, BlockRecord],
        header_blocks: Dict[bytes32, HeaderBlock],
    ) -> Optional[VDFInfo]:
        curr = blocks[header_block.header_hash]
        while curr.height > 0 and not curr.sub_epoch_summary_included:
            curr = blocks[curr.prev_hash]
        return header_blocks[curr.header_hash].finished_sub_slots[-1].reward_chain.end_of_slot_vdf

    async def __slot_end_vdf(
        self, start_height: uint32, header_blocks: Dict[bytes32, HeaderBlock], blocks: Dict[bytes32, BlockRecord]
    ) -> Tuple[Optional[List[SubSlotDataV2]], uint32]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        log.debug(f"slot end vdf start height {start_height}")
        curr = header_blocks[self.blockchain.height_to_hash(start_height)]
        sub_slots_data: List[SubSlotDataV2] = []
        tmp_sub_slots_data: List[SubSlotDataV2] = []
        while not blocks[curr.header_hash].is_challenge_block(self.constants):
            if curr.first_in_sub_slot:
                sub_slots_data.extend(tmp_sub_slots_data)
                # add collected vdfs
                for idx, sub_slot in enumerate(curr.finished_sub_slots):
                    prev_rec = blocks[curr.prev_header_hash]
                    sub_slots_data.append(handle_finished_slots(sub_slot, prev_rec.deficit))
                tmp_sub_slots_data = []
            # if overflow block and challenge slot ended break
            if blocks[curr.header_hash].deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                break
            tmp_sub_slots_data.append(self.handle_block_vdfs(curr, blocks))
            curr = header_blocks[self.blockchain.height_to_hash(uint32(curr.height + 1))]

        log.debug(f"slot end vdf end height {curr.height} ")
        return sub_slots_data, curr.height

    def handle_block_vdfs(self, curr: HeaderBlock, blocks: Dict[bytes32, BlockRecord]):
        cc_sp_proof = None
        cc_sp_output = None
        if curr.challenge_chain_sp_proof is not None:
            assert curr.reward_chain_block.challenge_chain_sp_vdf
            cc_sp_output = curr.reward_chain_block.challenge_chain_sp_vdf.output
            cc_sp_proof = curr.challenge_chain_sp_proof
        return SubSlotDataV2(
            None,
            cc_sp_proof,
            curr.challenge_chain_ip_proof,
            curr.reward_chain_block.signage_point_index,
            None,
            None if cc_sp_output is None else cc_sp_output,
            curr.reward_chain_block.challenge_chain_ip_vdf.output,
            None,
            None,
            blocks[curr.header_hash].ip_iters(self.constants),
            curr.total_iters,
        )


def vars_to_bytes(constants, summaries, weight_proof):
    constants_dict = recurse_jsonify(dataclasses.asdict(constants))
    wp_recent_chain_bytes = bytes(RecentChainData(weight_proof.recent_chain_data))
    wp_segment_bytes = bytes(SubEpochSegmentsV2(weight_proof.sub_epoch_segments))
    summary_bytes = []
    for summary in summaries:
        summary_bytes.append(bytes(summary))
    return constants_dict, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes


def bytes_to_vars(constants_dict, summaries_bytes):
    summaries = []
    for summary in summaries_bytes:
        summaries.append(SubEpochSummary.from_bytes(summary))
    constants: ConsensusConstants = dataclass_from_dict(ConsensusConstants, constants_dict)
    return constants, summaries


def _get_weights_for_sampling(rng: random.Random, total_weight: uint128, last_l_weight) -> Optional[List[uint128]]:
    weight_to_check = []
    delta = last_l_weight / total_weight
    prob_of_adv_succeeding = 1 - math.log(WeightProofHandlerV2.C, delta)
    if prob_of_adv_succeeding <= 0:
        return None
    queries = -WeightProofHandlerV2.LAMBDA_L * math.log(2, prob_of_adv_succeeding)
    for i in range(int(queries) + 1):
        u = rng.random()
        q = 1 - delta ** u
        # todo check division and type conversions
        weight = q * float(total_weight)
        weight_to_check.append(uint128(weight))
    weight_to_check.sort()
    return weight_to_check


def _sample_sub_epoch(
    start_of_epoch_weight: uint128,
    end_of_epoch_weight: uint128,
    weight_to_check: List[uint128],
) -> bool:
    """
    weight_to_check: List[uint128] is expected to be sorted
    """
    if weight_to_check is None:
        return True
    if weight_to_check[-1] < start_of_epoch_weight:
        return False
    if weight_to_check[0] > end_of_epoch_weight:
        return False
    choose = False
    for weight in weight_to_check:
        if weight > end_of_epoch_weight:
            return False
        if start_of_epoch_weight < weight < end_of_epoch_weight:
            log.debug(f"start weight: {start_of_epoch_weight}")
            log.debug(f"weight to check {weight}")
            log.debug(f"end weight: {end_of_epoch_weight}")
            choose = True
            break

    return choose


# wp creation methods
def _create_sub_epoch_data(
    sub_epoch_summary: SubEpochSummary,
) -> SubEpochData:
    reward_chain_hash: bytes32 = sub_epoch_summary.reward_chain_hash
    #  Number of subblocks overflow in previous slot
    previous_sub_epoch_overflows: uint8 = sub_epoch_summary.num_blocks_overflow  # total in sub epoch - expected
    #  New work difficulty and iterations per sub-slot
    sub_slot_iters: Optional[uint64] = sub_epoch_summary.new_sub_slot_iters
    new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty
    return SubEpochData(reward_chain_hash, previous_sub_epoch_overflows, sub_slot_iters, new_difficulty)


async def _challenge_block_vdfs(
    constants: ConsensusConstants,
    header_block: HeaderBlock,
    block_rec: BlockRecord,
    blocks: Dict[bytes32, BlockRecord],
):

    (_, _, _, _, cc_vdf_iters, _,) = get_signage_point_vdf_info(
        constants,
        header_block.finished_sub_slots,
        block_rec.overflow,
        None if header_block.height == 0 else blocks[header_block.prev_header_hash],
        BlockCache(blocks),
        block_rec.sp_total_iters(constants),
        block_rec.sp_iters(constants),
    )
    cc_sp_info = None
    if header_block.reward_chain_block.challenge_chain_sp_vdf:
        cc_sp_info = header_block.reward_chain_block.challenge_chain_sp_vdf
    ssd = SubSlotDataV2(
        header_block.reward_chain_block.proof_of_space,
        header_block.challenge_chain_sp_proof,
        header_block.challenge_chain_ip_proof,
        header_block.reward_chain_block.signage_point_index,
        None,
        None if cc_sp_info is None else cc_sp_info.output,
        header_block.reward_chain_block.challenge_chain_ip_vdf.output,
        None,
        None,
        block_rec.ip_iters(constants),
        block_rec.total_iters,
    )
    return ssd


def handle_finished_slots(end_of_slot: EndOfSubSlotBundle, prev_deficit: uint8):
    curr_icc_info = None
    if end_of_slot.infused_challenge_chain is not None:
        curr_icc_info = end_of_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
    return SubSlotDataV2(
        None,
        None,
        None,
        None,
        end_of_slot.proofs.challenge_chain_slot_proof,
        None,
        None,
        end_of_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output,
        curr_icc_info if prev_deficit == 0 else None,
        None,
        None,
    )


def compress_segments(
    full_segment_index, segments: List[SubEpochChallengeSegmentV2]
) -> List[SubEpochChallengeSegmentV2]:
    compressed_segments = []
    compressed_segments.append(segments[0])
    for idx, segment in enumerate(segments[1:]):
        if idx != full_segment_index:
            # remove all redundant values
            segment = compress_segment(segment)
        compressed_segments.append(segment)
    return compressed_segments


def compress_segment(segment: SubEpochChallengeSegmentV2) -> SubEpochChallengeSegmentV2:
    # find challenge slot
    comp_seg = SubEpochChallengeSegmentV2(
        segment.sub_epoch_n, [], segment.rc_slot_end_info, segment.cc_slot_end_iterations, None
    )
    for slot in segment.sub_slot_data:
        comp_seg.sub_slot_data.append(slot)
        if slot.is_challenge():
            break
    return segment


# ///////////////////////
# wp validation methods
# //////////////////////
def _validate_sub_epoch_summaries(
    constants: ConsensusConstants,
    weight_proof: WeightProofV2,
) -> Tuple[Optional[List[SubEpochSummary]], Optional[List[uint128]]]:

    last_ses_hash, last_ses_sub_height, last_ses_sub_weight = _get_last_ses(constants, weight_proof.recent_chain_data)
    if last_ses_hash is None:
        log.warning("could not find last ses block")
        return None, None

    summaries, total, sub_epoch_weight_list = _map_sub_epoch_summaries(
        constants.SUB_EPOCH_BLOCKS,
        constants.GENESIS_CHALLENGE,
        weight_proof.sub_epochs,
        constants.DIFFICULTY_STARTING,
    )

    log.info(f"validating {len(summaries)} sub epochs, sub epoch data weight {total}")
    # validate weight
    if not _validate_summaries_weight(constants, total, summaries, weight_proof):
        log.error("failed validating weight")
        return None, None

    # add last ses weight from recent chain
    sub_epoch_weight_list.append(last_ses_sub_weight)
    last_ses = summaries[-1]
    log.debug(f"last ses sub height {last_ses_sub_height}")
    # validate last ses_hash
    if last_ses.get_hash() != last_ses_hash:
        log.error(f"failed to validate ses hashes block height {last_ses_sub_height}")
        return None, None

    return summaries, sub_epoch_weight_list


def _map_sub_epoch_summaries(
    sub_blocks_for_se: uint32,
    ses_hash: bytes32,
    sub_epoch_data: List[SubEpochData],
    curr_difficulty: uint64,
) -> Tuple[List[SubEpochSummary], uint128, List[uint128]]:
    total_weight: uint128 = uint128(0)
    summaries: List[SubEpochSummary] = []
    sub_epoch_weight_list: List[uint128] = []
    for idx, data in enumerate(sub_epoch_data):
        ses = SubEpochSummary(
            ses_hash,
            data.reward_chain_hash,
            data.num_blocks_overflow,
            data.new_difficulty,
            data.new_sub_slot_iters,
        )

        if idx < len(sub_epoch_data) - 1:
            delta = sub_epoch_data[idx].num_blocks_overflow
            log.debug(f"sub epoch {idx} start weight is {total_weight+curr_difficulty} ")
            sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
            total_weight = total_weight + uint128(  # type: ignore
                curr_difficulty * (sub_blocks_for_se + sub_epoch_data[idx + 1].num_blocks_overflow - delta)
            )

        # if new epoch update diff and iters
        if data.new_difficulty is not None:
            curr_difficulty = data.new_difficulty

        # add to dict
        summaries.append(ses)
        ses_hash = std_hash(ses)
    # add last sub epoch weight
    sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
    return summaries, total_weight, sub_epoch_weight_list


def _validate_summaries_weight(constants: ConsensusConstants, sub_epoch_data_weight, summaries, weight_proof) -> bool:
    num_over = summaries[-1].num_blocks_overflow
    ses_end_height = (len(summaries) - 1) * constants.SUB_EPOCH_BLOCKS + num_over - 1
    curr = None
    for block in weight_proof.recent_chain_data:
        if block.reward_chain_block.height == ses_end_height:
            curr = block
    if curr is None:
        return False

    return curr.reward_chain_block.weight == sub_epoch_data_weight


def _validate_sub_epoch_segments(
    constants_dict: Dict,
    rng: random.Random,
    weight_proof_bytes: bytes,
    summaries_bytes: List[bytes],
):
    constants, summaries = bytes_to_vars(constants_dict, summaries_bytes)
    sub_epoch_segments: SubEpochSegmentsV2 = SubEpochSegmentsV2.from_bytes(weight_proof_bytes)
    rc_sub_slot_hash = constants.GENESIS_CHALLENGE
    total_blocks, total_ip_iters = 0, 0
    total_slot_iters, total_slots = 0, 0
    total_ip_iters = 0
    prev_ses: Optional[SubEpochSummary] = None
    segments_by_sub_epoch = map_segments_by_sub_epoch(sub_epoch_segments.challenge_segments)
    for sub_epoch_n, segments in segments_by_sub_epoch.items():
        log.debug(f"validate sub epoch {sub_epoch_n}")
        # recreate RewardChainSubSlot for next ses rc_hash
        sampled_seg_index = rng.choice(range(len(segments)))
        if sub_epoch_n == 0:
            cc_sub_slot_hash = constants.GENESIS_CHALLENGE
        else:
            rc_sub_slot = __get_rc_sub_slot(
                constants,
                segments[0],
                summaries,
            )
            if rc_sub_slot is None:
                log.error("failed getting rc sub slot")
                return False
            prev_ses = summaries[sub_epoch_n - 1]
            rc_sub_slot_hash = rc_sub_slot.get_hash()
            cc_sub_slot_hash = segments[0].cc_slot_end_challenge
        if not summaries[sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
            log.error(f"failed reward_chain_hash validation sub_epoch {sub_epoch_n}")
            return False
        curr_difficulty, curr_ssi = _get_curr_diff_ssi(constants, sub_epoch_n, summaries)

        for idx, segment in enumerate(segments):
            log.debug(f"validate segment {idx}")
            res = _validate_segment(
                constants,
                segment.sub_slot_data,
                curr_ssi,
                curr_difficulty,
                prev_ses,
                sampled_seg_index == idx,
                cc_sub_slot_hash,
            )
            if res is None:
                log.error(f"failed to validate sub_epoch {segment.sub_epoch_n} segment {idx} slots")
                return False
            valid_segment, ip_iters, slot_iters, slots, cc_sub_slot_hash = res
            log.debug(f"cc sub slot hash {cc_sub_slot_hash}")
            if prev_ses is not None:
                if prev_ses.new_sub_slot_iters is not None:
                    curr_ssi = prev_ses.new_sub_slot_iters
                if prev_ses.new_difficulty is not None:
                    curr_difficulty = prev_ses.new_difficulty
                prev_ses = None

            total_blocks += 1
            total_slot_iters += slot_iters
            total_slots += slots
            total_ip_iters += ip_iters
    avg_ip_iters = total_ip_iters / total_blocks
    avg_slot_iters = total_slot_iters / total_slots
    if avg_slot_iters / avg_ip_iters < float(constants.WEIGHT_PROOF_THRESHOLD):
        log.error(f"bad avg challenge block positioning ratio: {avg_slot_iters / avg_ip_iters}")
        return False
    return True


def _validate_segment(
    constants: ConsensusConstants,
    sub_slot_data: List[SubSlotDataV2],
    curr_ssi: uint64,
    curr_difficulty: uint64,
    ses: Optional[SubEpochSummary],
    sampled: bool,
    cc_sub_slot_hash,
) -> Optional[Tuple[bool, int, int, int, bytes32]]:
    ip_iters, slot_iters, slots = uint64(0), 0, 0
    after_challenge = False
    ssi = curr_ssi
    if ses is not None and ses.new_sub_slot_iters is not None:
        ssi = ses.new_sub_slot_iters
    prev_hash = None
    for idx, ssd in enumerate(sub_slot_data):
        if ssd.is_challenge():
            assert ssd.ip_iters
            ip_iters = ssd.ip_iters
        if sampled:
            # sampled se validate vdfs
            if ssd.is_challenge():
                assert cc_sub_slot_hash is not None
                assert ssd.signage_point_index is not None
                pospace_challenge = cc_sub_slot_hash
                if is_overflow_block(constants, ssd.signage_point_index):
                    pospace_challenge = prev_hash
                required_iters = __validate_pospace(
                    constants, sub_slot_data, idx, curr_difficulty, pospace_challenge, ssi
                )
                if required_iters is None:
                    return None
                if not _validate_challenge_sub_slot_data(
                    constants, idx, sub_slot_data, ssi, cc_sub_slot_hash, prev_hash
                ):
                    log.error(f"failed to validate challenge slot {idx} vdfs")
                    return None
                after_challenge = True
            elif after_challenge:
                if ssd.is_end_of_slot():
                    if not validate_cc_eos(cc_sub_slot_hash, constants, sub_slot_data[idx - 1], ssi, ssd):
                        log.error(f"failed to validate end of sub slot {idx} vdfs")
                        return None
                else:
                    if not _validate_sub_slot_data(constants, idx, sub_slot_data, ssi, cc_sub_slot_hash, prev_hash):
                        log.error(f"failed to validate sub slot data {idx} vdfs")
                        return None

        if ssd.is_end_of_slot():
            prev_hash = cc_sub_slot_hash
            icc_vdf = ssd.icc_slot_end_info
            icc_vdf_hash: Optional[bytes32] = None
            if icc_vdf is not None:
                icc_vdf_hash = icc_vdf.get_hash()
            assert ssd.cc_slot_end_output
            cc_vdf_info = VDFInfo(prev_hash, curr_ssi, ssd.cc_slot_end_output)
            cc_sub_slot = ChallengeChainSubSlot(
                cc_vdf_info,
                icc_vdf_hash,
                None if ses is None else ses.get_hash(),
                None if ses is None else ses.new_sub_slot_iters,
                None if ses is None else ses.new_difficulty,
            )
            ses = None
            log.debug(f"cc sub slot {cc_sub_slot} {cc_sub_slot.get_hash()}")
            cc_sub_slot_hash = cc_sub_slot.get_hash()
            curr_ssi = ssi
            slot_iters = slot_iters + curr_ssi  # type: ignore
            slots = uint64(slots + 1)
    return True, ip_iters, slot_iters, slots, cc_sub_slot_hash


def validate_cc_eos(cc_sub_slot_hash, constants, prev_ssd, ssi, sub_slot_data):
    cc_eos_iters = ssi
    input = ClassgroupElement.get_default_element()
    if not prev_ssd.is_end_of_slot():
        if not sub_slot_data.cc_slot_end.normalized_to_identity:
            assert prev_ssd.cc_ip_vdf_output
            input = prev_ssd.cc_ip_vdf_output
            cc_eos_iters = ssi - prev_ssd.ip_iters
    assert sub_slot_data.cc_slot_end_output
    cc_slot_end_info = VDFInfo(
        cc_sub_slot_hash,
        cc_eos_iters,
        sub_slot_data.cc_slot_end_output,
    )
    assert sub_slot_data.cc_slot_end
    if not sub_slot_data.cc_slot_end.is_valid(constants, input, cc_slot_end_info):
        log.error(f"failed cc slot end validation  {cc_slot_end_info} \n input {input}")
        return False
    return True


def _validate_challenge_sub_slot_data(
    constants: ConsensusConstants,
    sub_slot_idx: int,
    sub_slots: List[SubSlotDataV2],
    ssi: uint64,
    challenge: bytes32,
    prev_challenge,
) -> bool:
    sub_slot_data = sub_slots[sub_slot_idx]
    prev_ssd = None
    if sub_slot_idx > 0:
        prev_ssd = sub_slots[sub_slot_idx - 1]
    assert sub_slot_data.signage_point_index is not None
    if sub_slot_data.cc_signage_point:
        is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
        sp_iters: uint64 = calculate_sp_iters(constants, ssi, sub_slot_data.signage_point_index)
        iterations = sp_iters
        sp_challenge = challenge
        assert sub_slot_data.cc_sp_vdf_output
        input = ClassgroupElement.get_default_element()
        if is_overflow:
            sp_challenge = prev_challenge
        if sub_slot_idx > 0 and not sub_slot_data.cc_signage_point.normalized_to_identity:
            sp_total_iters = get_sp_total_iters(sp_iters, is_overflow, ssi, sub_slot_data)
            input, iterations = sub_slot_data_vdf_info(sub_slot_idx, sub_slots, is_overflow, sp_total_iters, sp_iters)
        cc_sp_vdf_info = VDFInfo(sp_challenge, iterations, sub_slot_data.cc_sp_vdf_output)
        if not sub_slot_data.cc_signage_point.is_valid(constants, input, cc_sp_vdf_info):
            log.error(f"failed cc signage point vdf validation  {cc_sp_vdf_info}")
            return False
    input = ClassgroupElement.get_default_element()
    assert sub_slot_data.cc_infusion_point
    ip_vdf_iters = sub_slot_data.ip_iters
    if (
        sub_slot_idx > 0
        and not sub_slot_data.cc_infusion_point.normalized_to_identity
        and prev_ssd is not None
        and not prev_ssd.is_end_of_slot()
    ):
        assert sub_slot_data
        assert sub_slot_data.total_iters
        assert prev_ssd.total_iters
        assert prev_ssd.cc_ip_vdf_output
        input = prev_ssd.cc_ip_vdf_output
        ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
    assert ip_vdf_iters
    assert sub_slot_data.cc_ip_vdf_output
    cc_ip_vdf_info = VDFInfo(challenge, ip_vdf_iters, sub_slot_data.cc_ip_vdf_output)
    if not sub_slot_data.cc_infusion_point.is_valid(constants, input, cc_ip_vdf_info):
        log.error(f"failed cc infusion point vdf validation  {cc_ip_vdf_info} {challenge}")
        return False
    return True


def _validate_sub_slot_data(
    constants: ConsensusConstants,
    sub_slot_idx: int,
    sub_slots: List[SubSlotDataV2],
    ssi: uint64,
    cc_sub_slot_hash: bytes32,
    prev_cc_sub_slot_hash: bytes32,
) -> bool:
    sub_slot_data = sub_slots[sub_slot_idx]
    prev_ssd = sub_slots[sub_slot_idx - 1]
    # find end of slot
    idx = sub_slot_idx
    while idx < len(sub_slots) - 1:
        curr_slot = sub_slots[idx]
        if curr_slot.is_end_of_slot():
            # dont validate intermediate vdfs if slot is blue boxed
            assert curr_slot.cc_slot_end
            if curr_slot.cc_slot_end.normalized_to_identity is True:
                log.debug(f"skip intermediate vdfs slot {sub_slot_idx}")
                return True
            else:
                break
        idx += 1
    assert sub_slot_data.signage_point_index is not None

    if sub_slot_data.cc_signage_point:
        is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
        assert sub_slot_data.cc_sp_vdf_output
        sp_iters = calculate_sp_iters(constants, ssi, sub_slot_data.signage_point_index)
        input = ClassgroupElement.get_default_element()
        iterations = sp_iters
        challenge = cc_sub_slot_hash
        if is_overflow:
            challenge = prev_cc_sub_slot_hash
        if not sub_slot_data.cc_signage_point.normalized_to_identity:
            sp_total_iters = get_sp_total_iters(sp_iters, is_overflow, ssi, sub_slot_data)
            input, iterations = sub_slot_data_vdf_info(sub_slot_idx, sub_slots, is_overflow, sp_total_iters, sp_iters)
        cc_sp_vdf_info = VDFInfo(
            challenge,
            iterations,
            sub_slot_data.cc_sp_vdf_output,
        )
        if not sub_slot_data.cc_signage_point.is_valid(constants, input, cc_sp_vdf_info):
            log.error(f"failed cc signage point vdf validation  {cc_sp_vdf_info} {input}")
            return False
    input = ClassgroupElement.get_default_element()
    assert sub_slot_data.cc_infusion_point
    ip_vdf_iters = sub_slot_data.ip_iters
    if not sub_slot_data.cc_infusion_point.normalized_to_identity and not prev_ssd.is_end_of_slot():
        assert prev_ssd.cc_ip_vdf_output
        input = prev_ssd.cc_ip_vdf_output
        assert sub_slot_data.total_iters
        assert prev_ssd.total_iters
        ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
    assert sub_slot_data.cc_ip_vdf_output
    assert ip_vdf_iters is not None
    cc_ip_vdf_info = VDFInfo(cc_sub_slot_hash, ip_vdf_iters, sub_slot_data.cc_ip_vdf_output)
    if not sub_slot_data.cc_infusion_point.is_valid(constants, input, cc_ip_vdf_info):
        log.error(f"failed cc infusion point vdf validation  {cc_ip_vdf_info} {prev_cc_sub_slot_hash}")
        return False
    return True


def sub_slot_data_vdf_info(
    sub_slot_idx: int,
    sub_slots: List[SubSlotDataV2],
    is_overflow: bool,
    sp_total_iters: uint128,
    sp_iters: uint64,
) -> Tuple[ClassgroupElement, uint64]:
    ssd: Optional[SubSlotDataV2] = None
    slots_n = 1
    if is_overflow:
        slots_n = 2
    slots_seen = 0
    for ssd_idx in reversed(range(0, sub_slot_idx)):
        ssd = sub_slots[ssd_idx]
        assert ssd is not None
        if ssd.is_end_of_slot():
            slots_seen += 1
            if slots_seen == slots_n:
                break
        else:
            assert ssd.total_iters
            if not (ssd.total_iters > sp_total_iters):
                break
    assert ssd is not None
    if not ssd.is_end_of_slot():
        assert ssd.total_iters
        if ssd.total_iters < sp_total_iters:
            assert ssd.cc_ip_vdf_output
            return ssd.cc_ip_vdf_output, uint64(sp_total_iters - ssd.total_iters)
    return ClassgroupElement.get_default_element(), sp_iters

def _validate_recent_blocks(constants_dict: Dict, recent_chain_bytes: bytes, summaries_bytes: List[bytes]) -> bool:
    constants, summaries = bytes_to_vars(constants_dict, summaries_bytes)
    recent_chain: RecentChainData = RecentChainData.from_bytes(recent_chain_bytes)
    sub_blocks = BlockCache({})
    first_ses_idx = _get_ses_idx(recent_chain.recent_chain_data)
    ses_idx = len(summaries) - len(first_ses_idx)
    ssi: uint64 = constants.SUB_SLOT_ITERS_STARTING
    diff: Optional[uint64] = constants.DIFFICULTY_STARTING
    last_blocks_to_validate = 100  # todo remove cap after benchmarks
    for summary in summaries[:ses_idx]:
        if summary.new_sub_slot_iters is not None:
            ssi = summary.new_sub_slot_iters
        if summary.new_difficulty is not None:
            diff = summary.new_difficulty

    ses_blocks, sub_slots, transaction_blocks = 0, 0, 0
    challenge, prev_challenge = None, None
    tip_height = recent_chain.recent_chain_data[-1].height
    prev_block_record = None
    deficit = uint8(0)
    for idx, block in enumerate(recent_chain.recent_chain_data):
        required_iters = uint64(0)
        overflow = False
        ses = False
        height = block.height
        for sub_slot in block.finished_sub_slots:
            prev_challenge = challenge
            challenge = sub_slot.challenge_chain.get_hash()
            deficit = sub_slot.reward_chain.deficit
            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                ses = True
                assert summaries[ses_idx].get_hash() == sub_slot.challenge_chain.subepoch_summary_hash
                ses_idx += 1
            if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                ssi = sub_slot.challenge_chain.new_sub_slot_iters
            if sub_slot.challenge_chain.new_difficulty is not None:
                diff = sub_slot.challenge_chain.new_difficulty

        if (challenge is not None) and (prev_challenge is not None):
            overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
            deficit = get_deficit(constants, deficit, prev_block_record, overflow, len(block.finished_sub_slots))
            log.debug(f"wp, validate block {block.height}")
            if sub_slots > 2 and transaction_blocks > 11 and (tip_height - block.height < last_blocks_to_validate):
                required_iters, error = validate_finished_header_block(
                    constants, sub_blocks, block, False, diff, ssi, ses_blocks > 2
                )
                if error is not None:
                    log.error(f"block {block.header_hash} failed validation {error}")
                    return False
            else:
                required_iters = _validate_pospace_recent_chain(
                    constants, block, challenge, diff, overflow, prev_challenge
                )
                if required_iters is None:
                    return False

        curr_block_ses = None if not ses else summaries[ses_idx - 1]
        block_record = header_block_to_sub_block_record(
            constants, required_iters, block, ssi, overflow, deficit, height, curr_block_ses
        )
        log.debug(f"add block {block_record.height} to tmp sub blocks")
        sub_blocks.add_block_record(block_record)

        if block.first_in_sub_slot:
            sub_slots += 1
        if block.is_transaction_block:
            transaction_blocks += 1
        if ses:
            ses_blocks += 1
        prev_block_record = block_record

    return True


def _validate_pospace_recent_chain(
    constants: ConsensusConstants,
    block: HeaderBlock,
    challenge: bytes32,
    diff: uint64,
    overflow: bool,
    prev_challenge: bytes32,
):
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        # Edge case of first sp (start of slot), where sp_iters == 0
        cc_sp_hash: bytes32 = challenge
    else:
        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
    assert cc_sp_hash is not None
    q_str = block.reward_chain_block.proof_of_space.verify_and_get_quality_string(
        constants,
        challenge if not overflow else prev_challenge,
        cc_sp_hash,
    )
    if q_str is None:
        log.error(f"could not verify proof of space block {block.height} {overflow}")
        return None
    required_iters = calculate_iterations_quality(
        constants.DIFFICULTY_CONSTANT_FACTOR,
        q_str,
        block.reward_chain_block.proof_of_space.size,
        diff,
        cc_sp_hash,
    )
    return required_iters


def __validate_pospace(
    constants: ConsensusConstants,
    sub_slot_data: List[SubSlotDataV2],
    idx: int,
    curr_diff: uint64,
    cc_sub_slot_hash: bytes32,
    ssi: uint64,
) -> Optional[uint64]:
    ssd: SubSlotDataV2 = sub_slot_data[idx]
    assert ssd.signage_point_index is not None
    sp_iters = calculate_sp_iters(constants, ssi, ssd.signage_point_index)
    if sp_iters == uint64(0):
        cc_sp_hash = cc_sub_slot_hash
    else:
        assert ssd.cc_sp_vdf_output
        cc_sp_hash = ssd.cc_sp_vdf_output.get_hash()

    # validate proof of space
    assert ssd.proof_of_space is not None
    q_str = ssd.proof_of_space.verify_and_get_quality_string(
        constants,
        cc_sub_slot_hash,
        cc_sp_hash,
    )
    if q_str is None:
        log.error("could not validate proof of space ")
        return None
    return calculate_iterations_quality(
        constants.DIFFICULTY_CONSTANT_FACTOR,
        q_str,
        ssd.proof_of_space.size,
        curr_diff,
        cc_sp_hash,
    )


def __get_rc_sub_slot(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegmentV2,
    summaries: List[SubEpochSummary],
) -> Optional[RewardChainSubSlot]:
    slots = segment.sub_slot_data
    ses = summaries[uint32(segment.sub_epoch_n - 1)]
    # find first block sub epoch
    first_idx = None
    first = None
    for idx, curr in enumerate(segment.sub_slot_data):
        if not curr.is_end_of_slot():
            first_idx = idx
            first = curr
            break

    if first_idx is None or first is None:
        log.error("could not find first block")
        return None

    # number of slots to look for
    slots_n = 1
    assert first.signage_point_index is not None
    overflow = is_overflow_block(constants, first.signage_point_index)
    new_diff = None if ses is None else ses.new_difficulty
    new_ssi = None if ses is None else ses.new_sub_slot_iters
    ses_hash = None if ses is None else ses.get_hash()

    if overflow:
        if first_idx >= 2 and slots[first_idx - 2].is_end_of_slot() is False:
            slots_n = 2
        if first_idx >= 2 and slots[first_idx - 2].is_end_of_slot() and slots[first_idx - 1].is_end_of_slot():
            ses_hash = None
            new_ssi = None
            new_diff = None

    challenge_slot = None
    for sub_slot in reversed(slots[:first_idx]):
        if sub_slot.is_end_of_slot():
            slots_n -= 1
            if slots_n == 0:
                challenge_slot = sub_slot
                break
    if slots_n > 0:
        log.error("not enough slots")
        return None

    assert challenge_slot is not None
    assert challenge_slot.cc_slot_end_output is not None
    icc_slot_end__hash = None
    assert segment.rc_slot_end_info is not None
    assert segment.cc_slot_end_iterations
    cc_vdf_info = VDFInfo(
        segment.cc_slot_end_challenge, segment.cc_slot_end_iterations, challenge_slot.cc_slot_end_output
    )
    if challenge_slot.icc_slot_end_info is not None:
        icc_slot_end__hash = challenge_slot.icc_slot_end_info.get_hash()
    cc_sub_slot = ChallengeChainSubSlot(
        cc_vdf_info,
        icc_slot_end__hash,
        ses_hash,
        new_ssi,
        new_diff,
    )

    rc_sub_slot = RewardChainSubSlot(
        segment.rc_slot_end_info,
        cc_sub_slot.get_hash(),
        icc_slot_end__hash,
        constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK,
    )
    log.debug(f"sub epoch start, cc sub slot {cc_sub_slot}")
    log.debug(f"sub epoch start, rc sub slot {rc_sub_slot}")
    return rc_sub_slot


def _get_curr_diff_ssi(constants: ConsensusConstants, idx, summaries):
    curr_difficulty = constants.DIFFICULTY_STARTING
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    if idx == 0:
        # genesis
        return curr_difficulty, curr_ssi
    for ses in reversed(summaries[0 : idx - 1]):
        if ses.new_sub_slot_iters is not None:
            curr_ssi = ses.new_sub_slot_iters
            curr_difficulty = ses.new_difficulty
            break

    return curr_difficulty, curr_ssi


def _get_last_ses(
    constants: ConsensusConstants, recent_reward_chain: List[HeaderBlock]
) -> Tuple[Optional[bytes32], uint32, uint128]:
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
                                curr.reward_chain_block.weight,
                            )
                idx += 1
    return None, uint32(0), uint128(0)


def _get_ses_idx(recent_reward_chain: List[HeaderBlock]) -> List[int]:
    idxs: List[int] = []
    for idx, curr in enumerate(recent_reward_chain):
        if len(curr.finished_sub_slots) > 0:
            for slot in curr.finished_sub_slots:
                if slot.challenge_chain.subepoch_summary_hash is not None:
                    idxs.append(idx)
    return idxs


def get_deficit(
    constants: ConsensusConstants,
    curr_deficit: uint8,
    prev_block: BlockRecord,
    overflow: bool,
    num_finished_sub_slots: int,
) -> uint8:
    if prev_block is None:
        if curr_deficit >= 1 and not (overflow and curr_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK):
            curr_deficit -= 1
        return curr_deficit

    return calculate_deficit(constants, uint32(prev_block.height + 1), prev_block, overflow, num_finished_sub_slots)


def get_sp_total_iters(sp_iters: uint64, is_overflow: bool, ssi: uint64, sub_slot_data: SubSlotDataV2) -> uint128:
    assert sub_slot_data.total_iters is not None
    assert sub_slot_data.signage_point_index is not None
    assert sub_slot_data.ip_iters
    ip_iters: uint64 = sub_slot_data.ip_iters
    sp_sub_slot_total_iters = uint128(sub_slot_data.total_iters - ip_iters)
    if is_overflow:
        sp_sub_slot_total_iters = uint128(sp_sub_slot_total_iters - ssi)
    return uint128(sp_sub_slot_total_iters + sp_iters)


def blue_boxed_end_of_slot(sub_slot: EndOfSubSlotBundle):
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
            if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                return True
        else:
            return True
    return False


def validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
    total_weight = sub_epoch_weight_list[-1]
    last_l_weight = sub_epoch_weight_list[-1] - sub_epoch_weight_list[-3]
    log.debug(f"total weight {total_weight} prev weight {sub_epoch_weight_list[-2]}")
    weight_to_check = _get_weights_for_sampling(rng, total_weight, last_l_weight)
    sampled_sub_epochs: dict[int, bool] = {}
    for idx in range(1, len(sub_epoch_weight_list)):
        if _sample_sub_epoch(sub_epoch_weight_list[idx - 1], sub_epoch_weight_list[idx], weight_to_check):
            sampled_sub_epochs[idx - 1] = True
            if len(sampled_sub_epochs) == WeightProofHandlerV2.MAX_SAMPLES:
                break
    curr_sub_epoch_n = -1
    for sub_epoch_segment in weight_proof.sub_epoch_segments:
        if curr_sub_epoch_n < sub_epoch_segment.sub_epoch_n:
            if sub_epoch_segment.sub_epoch_n in sampled_sub_epochs:
                del sampled_sub_epochs[sub_epoch_segment.sub_epoch_n]
        curr_sub_epoch_n = sub_epoch_segment.sub_epoch_n
    if len(sampled_sub_epochs) > 0:
        return False
    return True


def map_segments_by_sub_epoch(sub_epoch_segments) -> Dict[int, List[SubEpochChallengeSegmentV2]]:
    segments: Dict[int, List[SubEpochChallengeSegmentV2]] = {}
    curr_sub_epoch_n = -1
    for idx, segment in enumerate(sub_epoch_segments):
        if curr_sub_epoch_n < segment.sub_epoch_n:
            curr_sub_epoch_n = segment.sub_epoch_n
            segments[curr_sub_epoch_n] = []
        segments[curr_sub_epoch_n].append(segment)
    return segments
