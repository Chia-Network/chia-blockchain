import asyncio
import dataclasses
import logging
import math
import random
from concurrent.futures import as_completed
from concurrent.futures.process import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, Union

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import header_block_to_sub_block_record
from chia.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_sp_interval_iters,
    calculate_sp_iters,
    is_overflow_block,
)
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.types.blockchain_format.classgroup import B, ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeBlockInfo, ChallengeChainSubSlot, RewardChainSubSlot
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, compress_output, verify_compressed_vdf
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import (
    RecentChainData,
    SubEpochChallengeSegmentV2,
    SubEpochData,
    SubEpochSegmentsV2,
    SubSlotDataV2,
    WeightProofV2,
)
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import dataclass_from_dict, recurse_jsonify

log = logging.getLogger(__name__)


class WeightProofHandlerV2:
    """
    "https://eprint.iacr.org/2019/226.pdf  fly client paper "
    """

    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 140
    SUB_EPOCHS_RECENT_CHAIN = 2

    def __init__(
        self,
        constants: ConsensusConstants,
        blockchain: BlockchainInterface,
    ):
        self.peak: Optional[bytes32] = None
        self.proof: Optional[WeightProofV2] = None
        self.constants = constants
        self.blockchain = blockchain
        self.lock = asyncio.Lock()

    async def get_proof_of_weight(self, tip: bytes32, seed: bytes32) -> Optional[WeightProofV2]:

        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            log.error("unknown tip")
            return None

        if tip_rec.height < self.constants.WEIGHT_PROOF_BLOCK_MIN:
            log.debug("need at least 3 sub epochs for weight proof")
            return None

        async with self.lock:
            wp = await self._create_proof_of_weight(tip, seed)
            if wp is None:
                return None
            self.proof = wp
            self.peak = tip
            return wp

    def get_fork_point_no_validations(self, weight_proof: WeightProofV2) -> Tuple[bool, uint32]:
        log.debug("get fork point skip validations")
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)
        result = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if result is None:
            log.warning("weight proof failed to validate sub epoch summaries")
            return False, uint32(0)
        return True, self.get_fork_point(result[0])

    async def validate_weight_proof(
        self, weight_proof: WeightProofV2, seed: bytes32, skip_segments: bool = False
    ) -> Tuple[bool, uint32, List[SubEpochSummary], List[BlockRecord]]:
        """
        validates a WP
        returns validation result, fork point, list of summaries and the latest l blocks as block records
        """
        valid, summaries, records = await validate_weight_proof_no_fork_point(
            self.constants, weight_proof, seed, skip_segments
        )
        return valid, self.get_fork_point(summaries), summaries, records

    def get_fork_point(self, received_summaries: List[SubEpochSummary]) -> uint32:
        """
        given a list of SubEpochSummary finds the forkpoint with the local chain
        """
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

    async def _create_proof_of_weight(self, tip: bytes32, seed: bytes32) -> Optional[WeightProofV2]:
        """
        Creates a weight proof object
        the Weight proof contains:
        sub_epochs - a list of SubEpochData for each sub epoch summary in the chain
        sub_epoch_segments -  a list of SubEpochSegmentsV2 for each sampled sub epoch
        recent_chain_data - all the blocks from the previous to last sub epoch to the tip
        """
        peak_rec = self.blockchain.try_block_record(tip)
        if peak_rec is None:
            log.error("failed not tip in cache")
            return None
        log.info(f"create weight proof peak {tip} {peak_rec.height}")
        recent_chain_task: asyncio.Task[Optional[List[HeaderBlock]]] = asyncio.create_task(
            get_recent_chain(self.blockchain, peak_rec.height)
        )
        summary_heights: List[uint32] = self.blockchain.get_ses_heights()
        sub_epoch_data: List[SubEpochData] = []
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            if ses_height > peak_rec.height:
                break
            ses = self.blockchain.get_ses(ses_height)
            log.debug(f"handle sub epoch summary {sub_epoch_n} at height: {ses_height}  ")
            sub_epoch_data.append(
                SubEpochData(ses.reward_chain_hash, ses.num_blocks_overflow, ses.new_sub_slot_iters, ses.new_difficulty)
            )
        rng = random.Random(seed)
        last_ses_block, prev_prev_ses_block = await self.get_last_l(summary_heights, peak_rec.height)
        if last_ses_block is None or prev_prev_ses_block is None:
            log.error("failed getting chain last L")
            return None
        last_l_weight = uint128(last_ses_block.weight - prev_prev_ses_block.weight)
        log.debug(f"total weight {last_ses_block.weight} prev weight {prev_prev_ses_block.weight}")
        weight_to_check: Optional[List[uint128]] = _get_weights_for_sampling(rng, last_ses_block.weight, last_l_weight)
        if weight_to_check is None:
            log.debug("chain is too light, will choose all sub epochs until cap is reached")
        ses_blocks = await self.blockchain.get_block_records_at(summary_heights)
        if ses_blocks is None:
            log.error("failed pulling ses blocks from database")
            return None

        # set prev_ses to genesis
        prev_ses_block = await self.blockchain.get_block_record_from_db(self.height_to_hash(uint32(0)))
        if prev_ses_block is None:
            return None

        sub_epoch_segments_tasks: List[asyncio.Task[Optional[Tuple[bytes, int]]]] = []
        sample_n = 0
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            if ses_height > peak_rec.height:
                break

            # if we have enough sub_epoch samples, dont sample
            if sample_n >= self.MAX_SAMPLES:
                log.debug(f"reached sampled sub epoch cap {sample_n}")
                break
            # sample sub epoch
            # next sub block
            ses_block = ses_blocks[sub_epoch_n]
            if ses_block is None or ses_block.sub_epoch_summary_included is None:
                log.error("error while building proof")
                return None

            if _sample_sub_epoch(prev_ses_block.weight, ses_block.weight, weight_to_check):
                sample_n += 1
                sub_epoch_segments_tasks.append(
                    asyncio.create_task(self.__create_persist_sub_epoch(prev_ses_block, ses_block, uint32(sub_epoch_n)))
                )
            prev_ses_block = ses_block
        sub_epoch_segments = await asyncio.gather(*sub_epoch_segments_tasks)
        compress_sub_epoch_futures = []
        with ProcessPoolExecutor() as executor:
            for result in sub_epoch_segments:
                if result is None:
                    log.error("error getting sub epoch segments")
                    return None
                sub_epoch, num_of_segments = result
                sampled_seg_index = rng.choice(range(num_of_segments))
                compress_sub_epoch_futures.append(executor.submit(reduce_segments, sampled_seg_index, sub_epoch))
        compressed_sub_epochs = []
        for idx, future in enumerate(compress_sub_epoch_futures):
            if future.exception() is not None:
                log.error("error while compressing sub epoch")
                return None
            compressed_sub_epochs.append(future.result())

        recent_chain = await recent_chain_task
        if recent_chain is None:
            log.error("error getting recent chain")
            return None
        return WeightProofV2(sub_epoch_data, compressed_sub_epochs, recent_chain)

    async def get_last_l(
        self, summary_heights: List[uint32], peak: uint32
    ) -> Tuple[Optional[BlockRecord], Optional[BlockRecord]]:
        """
        returns the last ses and prev ses blocks
        """
        summaries_n = len(summary_heights)
        for idx, height in enumerate(reversed(summary_heights)):
            if height <= peak:
                if summaries_n - idx < 3:
                    log.warning("chain too short not enough sub epochs ")
                    return None, None
                last_ses_block = await self.blockchain.get_block_record_from_db(
                    self.height_to_hash(uint32(summary_heights[summaries_n - idx - 1]))
                )
                prev_prev_ses_block = await self.blockchain.get_block_record_from_db(
                    self.height_to_hash(uint32(summary_heights[summaries_n - idx - 3]))
                )
                return last_ses_block, prev_prev_ses_block
        return None, None

    async def create_sub_epoch_segments(self) -> None:
        """
        iterates through all sub epochs creates the corresponding segments
        and persists to the db segment table
        """
        log.debug("check segments in db")
        peak_height = self.blockchain.get_peak_height()
        if peak_height is None:
            log.error("no peak yet")
            return None

        summary_heights = self.blockchain.get_ses_heights()
        prev_ses_block = await self.blockchain.get_block_record_from_db(self.height_to_hash(uint32(0)))
        if prev_ses_block is None:
            return None

        ses_blocks = await self.blockchain.get_block_records_at(summary_heights)
        if ses_blocks is None:
            return None

        for sub_epoch_n, ses_block in enumerate(ses_blocks):
            log.info(f"check db for sub epoch {sub_epoch_n}")
            if ses_block.height > peak_height:
                break
            if ses_block is None or ses_block.sub_epoch_summary_included is None:
                log.error("error while building proof")
                return None
            log.debug(f"create segments for sub epoch {sub_epoch_n}")
            await self.__create_persist_sub_epoch(prev_ses_block, ses_block, uint32(sub_epoch_n))
            prev_ses_block = ses_block
        log.debug("done checking segments")
        return None

    async def __create_persist_sub_epoch(
        self, prev_ses_block: BlockRecord, ses_block: BlockRecord, sub_epoch_n: uint32
    ) -> Optional[Tuple[bytes, int]]:
        res = await self.blockchain.get_sub_epoch_challenge_segments_v2(ses_block.header_hash)
        if res is not None:
            return res[0], res[1]
        segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(sub_epoch_n))
        if segments is None:
            log.error(f"failed while building segments for sub epoch {sub_epoch_n}, ses height {ses_block.height} ")
            return None
        num_of_segments = len(segments)
        segments_bytes = bytes(SubEpochSegmentsV2(segments))
        await self.blockchain.persist_sub_epoch_challenge_segments_v2(
            ses_block.header_hash, segments_bytes, num_of_segments
        )
        return segments_bytes, num_of_segments

    async def create_prev_sub_epoch_segments(self) -> None:
        """
        creates and persists sub epoch segments for the prev sub epoch
        """
        log.debug("create prev sub_epoch_segments")
        heights = self.blockchain.get_ses_heights()
        if len(heights) < 3:
            return
        count = len(heights) - 2
        ses_sub_block = self.blockchain.height_to_block_record(heights[-2])
        prev_ses_sub_block = self.blockchain.height_to_block_record(heights[-3])
        segments = await self.__create_sub_epoch_segments(ses_sub_block, prev_ses_sub_block, uint32(count))
        assert segments is not None
        await self.blockchain.persist_sub_epoch_challenge_segments_v2(
            ses_sub_block.header_hash, bytes(SubEpochSegmentsV2(segments)), len(segments)
        )
        log.debug("sub_epoch_segments done")
        return

    async def check_prev_sub_epoch_segments(self) -> bool:
        """
        checks if db contains sub epoch segments
        """
        log.debug("create prev sub_epoch_segments")
        heights = self.blockchain.get_ses_heights()
        if len(heights) < 2:
            return True
        ses_block = self.blockchain.height_to_block_record(heights[-2])
        segment = await self.blockchain.get_sub_epoch_challenge_segments_v2(ses_block.header_hash)
        return segment is not None

    async def __create_sub_epoch_segments(
        self, ses_block: BlockRecord, se_start: BlockRecord, sub_epoch_n: uint32
    ) -> Optional[List[SubEpochChallengeSegmentV2]]:
        """
        returns a list of SubEpochChallengeSegmentV2 representing all challenge slots in the sub epoch
        uses the ProcessPoolExecutor to handle the conversions from CompressedElement to B
        """
        segments: List[SubEpochChallengeSegmentV2] = []
        start_height = await self.get_prev_two_slots_height(se_start)
        blocks = await self.blockchain.get_block_records_in_range(
            start_height, ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS
        )
        header_blocks = await self.blockchain.get_header_blocks_in_range(
            start_height, ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS, tx_filter=False
        )
        curr: Optional[HeaderBlock] = header_blocks[se_start.header_hash]
        assert curr is not None
        height = se_start.height
        first = True
        idx = 0
        with ProcessPoolExecutor() as executor:
            while curr.height < ses_block.height:
                if blocks[curr.header_hash].is_challenge_block(self.constants):
                    log.debug(f"challenge segment {idx}, starts at {curr.height} ")
                    seg, height = self._create_challenge_segment(
                        curr, sub_epoch_n, header_blocks, blocks, first, executor
                    )
                    if seg is None:
                        log.error(f"failed creating segment {curr.header_hash} ")
                        return None
                    segments.append(seg)
                    idx += 1
                    first = False
                else:
                    height = height + uint32(1)  # type: ignore
                curr = header_blocks[self.height_to_hash(height)]
                if curr is None:
                    log.error(f"failed creating segment, could not find block at height {height} ")
                    return None
        log.debug(f"next sub epoch starts at {height}")
        return segments

    async def get_prev_two_slots_height(self, se_start: BlockRecord) -> uint32:
        # find block height where the previous to last slot ended before the start of the sub epoch.
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
            curr_rec = blocks[self.height_to_hash(uint32(curr_rec.height - 1))]
        return curr_rec.height

    def _create_challenge_segment(
        self,
        header_block: HeaderBlock,
        sub_epoch_n: uint32,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
        first_segment_in_sub_epoch: bool,
        executor: ProcessPoolExecutor,
    ) -> Tuple[Optional[SubEpochChallengeSegmentV2], uint32]:
        """
        crete and return the SubEpochChallengeSegmentV2 representing the challenge segments starting at header_block
        """
        sub_slots: List[SubSlotDataV2] = []
        log.debug(f"create challenge segment block {header_block.header_hash} block height {header_block.height} ")
        # VDFs from sub slots before challenge block
        first_sub_slots, end_of_sub_slot_bundle = self.__first_sub_slot_vdfs(
            header_block, header_blocks, blocks, first_segment_in_sub_epoch, executor
        )
        if first_sub_slots is None:
            log.error("failed building first sub slots")
            return None, uint32(0)

        sub_slots.extend(first_sub_slots)
        sub_slots.append(handle_block_vdfs(executor, self.constants, header_block, blocks))

        # # VDFs from slot after challenge block to end of slot
        log.debug(f"create slot end vdf for block {header_block.header_hash} height {header_block.height}")
        challenge_slot_end_sub_slots, end_height = self.__slot_end_vdf(
            uint32(header_block.height + 1), header_blocks, blocks, executor
        )

        if challenge_slot_end_sub_slots is None:
            log.error("failed building slot end ")
            return None, uint32(0)
        sub_slots.extend(challenge_slot_end_sub_slots)
        if first_segment_in_sub_epoch and sub_epoch_n != 0:
            assert end_of_sub_slot_bundle is not None
            first_rc_end_of_slot_vdf = end_of_sub_slot_bundle.reward_chain.end_of_slot_vdf
            end_of_slot_info = end_of_sub_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf
            end_of_slot_icc_challenge = None
            if end_of_sub_slot_bundle.infused_challenge_chain is not None:
                end_of_slot_icc_challenge = (
                    end_of_sub_slot_bundle.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge
                )

            prev_icc_ip_iters = None
            slots_to_check = 1
            if not header_block.first_in_sub_slot:
                slots_to_check = 2
            curr = blocks[header_block.prev_header_hash]
            while not curr.is_challenge_block(self.constants):
                if curr.first_in_sub_slot:
                    slots_to_check -= 1
                    if slots_to_check == 0:
                        break
                curr = blocks[curr.prev_hash]
                if curr.is_challenge_block(self.constants):
                    prev_icc_ip_iters = curr.ip_iters(self.constants)
            return (
                SubEpochChallengeSegmentV2(
                    sub_epoch_n,
                    sub_slots,
                    first_rc_end_of_slot_vdf,
                    end_of_slot_info,
                    end_of_slot_icc_challenge,
                    prev_icc_ip_iters,
                ),
                end_height,
            )
        return SubEpochChallengeSegmentV2(sub_epoch_n, sub_slots, None, None, None, None), end_height

    def __first_sub_slot_vdfs(
        self,
        header_block: HeaderBlock,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
        first_in_sub_epoch: bool,
        executor: ProcessPoolExecutor,
    ) -> Tuple[Optional[List[SubSlotDataV2]], Optional[EndOfSubSlotBundle]]:
        """
        returns a list of SubSlotDataV2 representing all slots and blocks since the last challenge ended
        also includes EndOfSubSlotBundle if this is the start of the sub epoch
        """
        # find slot start
        curr_sub_rec = blocks[header_block.header_hash]

        while curr_sub_rec.height != 0 and blocks[curr_sub_rec.prev_hash].deficit != 0:
            curr_sub_rec = blocks[curr_sub_rec.prev_hash]
        end_of_slot_bundle = None
        if first_in_sub_epoch and curr_sub_rec.height > 0:
            if curr_sub_rec.sub_epoch_summary_included is None:
                log.error("expected sub epoch summary")
                return None, None
            end_of_slot_bundle = header_blocks[curr_sub_rec.header_hash].finished_sub_slots[-1]

        sub_slots_data: List[SubSlotDataV2] = []
        tmp_sub_slots_data: List[SubSlotDataV2] = []
        curr = header_blocks[curr_sub_rec.header_hash]
        log.debug(f"challenge starts at {curr.height}")
        while curr.height < header_block.height:
            if curr is None:
                log.error("failed fetching block")
                return None, None
            if curr.first_in_sub_slot:
                # if not blue boxed
                if not blue_boxed_end_of_slot(curr.finished_sub_slots[0]):
                    sub_slots_data.extend(tmp_sub_slots_data)
                for idx, sub_slot in enumerate(curr.finished_sub_slots):
                    sub_slots_data.append(handle_finished_slots(sub_slot))
                tmp_sub_slots_data = []
            tmp_sub_slots_data.append(handle_block_vdfs(executor, self.constants, curr, blocks))
            curr = header_blocks[self.height_to_hash(uint32(curr.height + 1))]

        if len(tmp_sub_slots_data) > 0:
            sub_slots_data.extend(tmp_sub_slots_data)

        for idx, sub_slot in enumerate(header_block.finished_sub_slots):
            sub_slots_data.append(handle_finished_slots(sub_slot))

        return sub_slots_data, end_of_slot_bundle

    def __slot_end_vdf(
        self,
        start_height: uint32,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
        executor: ProcessPoolExecutor,
    ) -> Tuple[Optional[List[SubSlotDataV2]], uint32]:
        """
        returns a list of SubSlotDataV2 representing all slots and blocks until
        the challenge slot ends
        """
        # gets all vdfs first sub slot after challenge block to last sub slot
        log.debug(f"slot end vdf start height {start_height}")
        curr = header_blocks[self.height_to_hash(start_height)]
        sub_slots_data: List[SubSlotDataV2] = []
        tmp_sub_slots_data: List[SubSlotDataV2] = []
        while not blocks[curr.header_hash].is_challenge_block(self.constants):
            if curr.first_in_sub_slot:
                # add collected vdfs
                sub_slots_data.extend(tmp_sub_slots_data)
                for idx, sub_slot in enumerate(curr.finished_sub_slots):
                    sub_slots_data.append(handle_finished_slots(sub_slot))
                tmp_sub_slots_data = []
            # if overflow block and challenge slot ended break
            # find input
            tmp_sub_slots_data.append(handle_block_vdfs(executor, self.constants, curr, blocks))
            curr = header_blocks[self.height_to_hash(uint32(curr.height + 1))]
            if blocks[curr.header_hash].deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                break

        if len(tmp_sub_slots_data) > 0:
            sub_slots_data.extend(tmp_sub_slots_data)
        log.debug(f"slot end vdf end height {curr.height} ")
        return sub_slots_data, curr.height

    # util to avoid asserting height in height_to_hash
    # the base assumption is that we have all the heights needed in height_to_hash
    def height_to_hash(self, height: uint32) -> bytes32:
        hash = self.blockchain.height_to_hash(height)
        assert hash
        return hash


def _get_weights_for_sampling(
    rng: random.Random, total_weight: uint128, last_l_weight: uint128
) -> Optional[List[uint128]]:
    weight_to_check = []
    delta = last_l_weight / total_weight
    prob_of_adv_succeeding = 1 - math.log(WeightProofHandlerV2.C, delta)
    if prob_of_adv_succeeding <= 0:
        return None
    queries = -WeightProofHandlerV2.LAMBDA_L * math.log(2, prob_of_adv_succeeding)
    for i in range(int(queries) + 1):
        u = rng.random()
        q = 1 - delta ** u
        weight = q * float(total_weight)
        weight_to_check.append(uint128(int(weight)))
    weight_to_check.sort()
    return weight_to_check


# wp creation methods


def handle_block_vdfs(
    executor: ProcessPoolExecutor,
    constants: ConsensusConstants,
    header_block: HeaderBlock,
    blocks: Dict[bytes32, BlockRecord],
) -> SubSlotDataV2:
    """
    returns a SubSlotDataV2 representing header_block
    uses B to replace ClassgroupElement for cc_sp, cc_ip, icc_ip
    """
    block_rec = blocks[header_block.header_hash]
    compressed_sp_output = None
    if header_block.challenge_chain_sp_proof is not None:
        assert header_block.reward_chain_block.challenge_chain_sp_vdf
        sp_input = ClassgroupElement.get_default_element()
        sp_iters = header_block.reward_chain_block.challenge_chain_sp_vdf.number_of_iterations
        if not header_block.challenge_chain_sp_proof.normalized_to_identity:
            (_, _, sp_input, _, _, sp_iters) = get_signage_point_vdf_info(
                constants,
                header_block.finished_sub_slots,
                block_rec.overflow,
                None if header_block.height == 0 else blocks[header_block.prev_header_hash],
                BlockCache(blocks),
                block_rec.sp_total_iters(constants),
                block_rec.sp_iters(constants),
            )
        compressed_sp_output = compress_output(
            constants.DISCRIMINANT_SIZE_BITS,
            header_block.reward_chain_block.challenge_chain_sp_vdf.challenge,
            sp_input,
            header_block.reward_chain_block.challenge_chain_sp_vdf.output,
            header_block.challenge_chain_sp_proof,
            sp_iters,
            executor,
        )
    cc_ip_input = ClassgroupElement.get_default_element()
    cc_ip_iters = block_rec.ip_iters(constants)
    prev_block = None
    if header_block.height > 0 and not block_rec.first_in_sub_slot:
        prev_block = blocks[header_block.prev_header_hash]
        if not header_block.challenge_chain_ip_proof.normalized_to_identity:
            cc_ip_input = prev_block.challenge_vdf_output
            cc_ip_iters = uint64(header_block.total_iters - prev_block.total_iters)
    compressed_cc_ip_output = compress_output(
        constants.DISCRIMINANT_SIZE_BITS,
        header_block.reward_chain_block.challenge_chain_ip_vdf.challenge,
        cc_ip_input,
        header_block.reward_chain_block.challenge_chain_ip_vdf.output,
        header_block.challenge_chain_ip_proof,
        cc_ip_iters,
        executor,
    )
    compressed_icc_ip_output = None
    if header_block.infused_challenge_chain_ip_proof is not None:
        icc_ip_iters = block_rec.ip_iters(constants)
        icc_ip_input = ClassgroupElement.get_default_element()
        if not block_rec.first_in_sub_slot:
            assert prev_block is not None
            icc_ip_iters = uint64(header_block.total_iters - prev_block.total_iters)
            if not prev_block.is_challenge_block(constants):
                assert prev_block.infused_challenge_vdf_output is not None
                icc_ip_input = prev_block.infused_challenge_vdf_output
        assert header_block.reward_chain_block.infused_challenge_chain_ip_vdf
        compressed_icc_ip_output = compress_output(
            constants.DISCRIMINANT_SIZE_BITS,
            header_block.reward_chain_block.infused_challenge_chain_ip_vdf.challenge,
            icc_ip_input,
            header_block.reward_chain_block.infused_challenge_chain_ip_vdf.output,
            header_block.infused_challenge_chain_ip_proof,
            icc_ip_iters,
            executor,
        )

    return SubSlotDataV2(
        header_block.reward_chain_block.proof_of_space if block_rec.is_challenge_block(constants) else None,
        header_block.challenge_chain_sp_proof,
        header_block.challenge_chain_ip_proof,
        header_block.reward_chain_block.signage_point_index,
        None,
        None if compressed_sp_output is None else B.from_hex(compressed_sp_output.result()),
        B.from_hex(compressed_cc_ip_output.result()),
        None,
        header_block.infused_challenge_chain_ip_proof,
        None if compressed_icc_ip_output is None else B.from_hex(compressed_icc_ip_output.result()),
        None,
        None,
        header_block.reward_chain_block.challenge_chain_sp_signature
        if block_rec.is_challenge_block(constants)
        else None,
        blocks[header_block.header_hash].ip_iters(constants),
        header_block.total_iters,
    )


# returns a SubSlotDataV2 representing the slot
def handle_finished_slots(end_of_slot: EndOfSubSlotBundle) -> SubSlotDataV2:
    icc_slot_end_output = None
    if end_of_slot.infused_challenge_chain is not None:
        icc_slot_end_output = end_of_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output
    return SubSlotDataV2(
        None,
        None,
        None,
        None,
        end_of_slot.proofs.challenge_chain_slot_proof,
        None,
        None,
        end_of_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output,
        None,
        None,
        end_of_slot.proofs.infused_challenge_chain_slot_proof,
        icc_slot_end_output,
        None,
        None,
        None,
    )


def reduce_segments(full_segment_index: int, segments_bytes: bytes) -> bytes:
    """
    given a sub epoch remove all the unneeded fields from the
    challenge segments not selected for validation
    """
    compressed_segments = []
    segments = SubEpochSegmentsV2.from_bytes(segments_bytes).challenge_segments
    for idx, segment in enumerate(segments):
        if idx == full_segment_index:
            compressed_segments.append(segment)
        else:
            # remove all redundant values
            comp_seg = SubEpochChallengeSegmentV2(
                segment.sub_epoch_n,
                [],
                segment.rc_slot_end_info,
                segment.cc_slot_end_info,
                segment.icc_sub_slot_hash,
                segment.prev_icc_ip_iters,
            )
            # find challenge slot
            after_challenge = False
            for subslot_data in segment.sub_slot_data:
                new_slot = subslot_data
                if after_challenge:
                    new_slot = SubSlotDataV2(
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        subslot_data.cc_slot_end_output,
                        None,
                        None,
                        None,
                        subslot_data.icc_slot_end_output,
                        None,
                        subslot_data.ip_iters,
                        None,
                    )
                if subslot_data.is_challenge():
                    after_challenge = True
                comp_seg.sub_slot_data.append(new_slot)
            compressed_segments.append(comp_seg)
    return bytes(SubEpochSegmentsV2(compressed_segments))


# ///////////////////////
# wp validation methods
# //////////////////////
def _validate_sub_epoch_summaries(
    constants: ConsensusConstants,
    weight_proof: WeightProofV2,
) -> Optional[Tuple[List[SubEpochSummary], List[uint128]]]:
    """
    converts weight_proof.sub_epochs to a list of SubEpochSummary by adding the missing ses_hash and rebuilding the
    SubEpochSummary object
    validates the weight and the last ses hash against the latest chain attached to the WP
    """
    last_ses_hash, last_ses_height, last_ses_sub_weight = _get_last_ses(constants, weight_proof.recent_chain_data)
    if last_ses_hash is None:
        log.warning("could not find last ses block")
        return None

    summaries, total, sub_epoch_weight_list = _map_sub_epoch_summaries(
        constants,
        weight_proof.sub_epochs,
    )

    log.info(f"validating {len(summaries)} sub epochs, sub epoch data weight {total}")
    # validate weight
    num_over = summaries[-1].num_blocks_overflow
    ses_end_height = (len(summaries) - 1) * constants.SUB_EPOCH_BLOCKS + num_over - 1
    curr = None
    for block in weight_proof.recent_chain_data:
        if block.reward_chain_block.height == ses_end_height:
            curr = block
    if curr is None or not curr.reward_chain_block.weight == total:
        log.error("failed validating weight")
        return None

    # add last ses weight from recent chain
    sub_epoch_weight_list.append(last_ses_sub_weight)
    last_ses = summaries[-1]
    log.debug(f"last ses height {last_ses_height}")
    # validate last ses_hash
    if last_ses.get_hash() != last_ses_hash:
        log.error(f"failed to validate ses hashes block height {last_ses_height}")
        return None

    return summaries, sub_epoch_weight_list


def _map_sub_epoch_summaries(
    constants: ConsensusConstants,
    sub_epoch_data: List[SubEpochData],
) -> Tuple[List[SubEpochSummary], uint128, List[uint128]]:

    total_weight: uint128 = uint128(0)
    summaries: List[SubEpochSummary] = []
    sub_epoch_weight_list: List[uint128] = []
    ses_hash = constants.GENESIS_CHALLENGE
    curr_difficulty = constants.DIFFICULTY_STARTING
    for idx, data in enumerate(sub_epoch_data):
        ses = SubEpochSummary(
            ses_hash,
            data.reward_chain_hash,
            data.num_blocks_overflow,
            data.new_difficulty,
            data.new_sub_slot_iters,
        )

        if idx < len(sub_epoch_data) - 1:
            log.debug(f"sub epoch {idx} start weight is {total_weight + curr_difficulty} ")
            sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
            extra_sub_epoch_blocks = (
                sub_epoch_data[idx + 1].num_blocks_overflow - sub_epoch_data[idx].num_blocks_overflow
            )
            total_weight = uint128(
                total_weight + uint128(curr_difficulty * (constants.SUB_EPOCH_BLOCKS + extra_sub_epoch_blocks))
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


def _validate_sub_epoch_segments(
    constants_dict: Dict[str, Any],
    rng: random.Random,
    sub_epoch_segments: List[bytes],
    summaries_bytes: List[bytes],
    executor: ProcessPoolExecutor,
) -> Tuple[bool, List[uint32]]:
    """
    validates all sub_epoch_segments in parallel using ProcessPoolExecutor
    """
    ses_validation_futures = []
    for segments in sub_epoch_segments:
        length = len(SubEpochSegmentsV2.from_bytes(segments).challenge_segments)
        sampled_seg_index = rng.choice(range(length))
        ses_validation_futures.append(
            executor.submit(
                validate_sub_epoch,
                constants_dict,
                sampled_seg_index,
                segments,
                summaries_bytes,
            )
        )
    sub_epochs = []
    for idx, future in enumerate(as_completed(ses_validation_futures)):
        log.debug(f"validated sub epoch sample {idx} out of {len(ses_validation_futures)}")
        if future.exception() is not None:
            log.error(f"error validating sub epoch sample {future.exception()}")
            return False, []
        sub_epochs.append(future.result())

    return True, sub_epochs


def validate_sub_epoch(
    constants_dict: Dict[str, Any],
    sampled_seg_index: int,
    segment_bytes: bytes,
    summaries_bytes: List[bytes],
) -> uint32:
    segments = SubEpochSegmentsV2.from_bytes(segment_bytes).challenge_segments
    sub_epoch_n: uint32 = segments[0].sub_epoch_n
    log.debug(f"validate sub epoch {sub_epoch_n}")
    prev_ses: Optional[SubEpochSummary] = None
    total_blocks, total_ip_iters, total_slot_iters, total_slots = 0, 0, 0, 0
    constants, summaries = bytes_to_vars(constants_dict, summaries_bytes)  # ignore [no-untyped-call]
    # recreate RewardChainSubSlot for next ses rc_hash
    curr_difficulty, curr_ssi = _get_curr_diff_ssi(constants, sub_epoch_n, summaries)
    start_idx = 0
    if sub_epoch_n == 0:
        rc_sub_slot_hash, cc_sub_slot_hash, icc_sub_slot_hash = (
            constants.GENESIS_CHALLENGE,
            constants.GENESIS_CHALLENGE,
            None,
        )
    else:
        prev_ses = summaries[sub_epoch_n - 1]
        rc_sub_slot_hash, start_idx = __get_rc_sub_slot_hash(constants, segments[0], summaries, curr_ssi)
        assert segments[0].cc_slot_end_info is not None
        cc_sub_slot_hash = segments[0].cc_slot_end_info.challenge
        icc_sub_slot_hash = segments[0].icc_sub_slot_hash
    if not summaries[sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
        raise Exception(f"failed reward_chain_hash validation sub_epoch {sub_epoch_n}")
    prev_challenge_ip_iters = uint64(0)
    slot_after_challenge = False
    for idx, segment in enumerate(segments):
        log.debug(f"validate segment {idx} sampled:{sampled_seg_index == idx}")
        res = _validate_segment(
            constants,
            segment,
            curr_ssi,
            curr_difficulty,
            prev_ses if idx == 0 else None,
            sampled_seg_index == idx,
            cc_sub_slot_hash,
            icc_sub_slot_hash,
            uint64(0) if slot_after_challenge else prev_challenge_ip_iters,
            start_idx if idx == 0 else 0,
        )
        prev_challenge_ip_iters, slot_iters, slots, cc_sub_slot_hash, icc_sub_slot_hash, slot_after_challenge = res
        log.debug(f"cc sub slot hash {cc_sub_slot_hash}")
        if prev_ses is not None and prev_ses.new_sub_slot_iters is not None:
            curr_ssi = prev_ses.new_sub_slot_iters
        if prev_ses is not None and prev_ses.new_difficulty is not None:
            curr_difficulty = prev_ses.new_difficulty

        total_blocks += 1
        total_slot_iters += slot_iters * slots
        total_slots += slots
        total_ip_iters += prev_challenge_ip_iters
    avg_ip_iters = total_ip_iters / total_blocks
    avg_slot_iters = total_slot_iters / total_slots
    if avg_slot_iters / avg_ip_iters < float(constants.WEIGHT_PROOF_THRESHOLD):
        raise Exception(
            f"bad avg challenge block positioning ratio: {avg_slot_iters / avg_ip_iters} sub_epoch {sub_epoch_n}"
        )
    return sub_epoch_n


def _validate_segment(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegmentV2,
    curr_ssi: uint64,
    curr_difficulty: uint64,
    ses: Optional[SubEpochSummary],
    sampled: bool,
    cc_challenge: bytes32,
    icc_challenge: Optional[bytes32],
    prev_challenge_ip_iters: uint64,
    start_from: int = 0,
) -> Tuple[uint64, uint64, int, bytes32, bytes32, bool]:
    """
    validates all segments
    if this is the "sampled" challenge segment we validate all the vdfs
    if not we validate all the hashes for the end of slots

    start_from is used for an edge case where this is the first segment
    of the sub epoch and there are multiple empty slots
    in that case we already have the end of slot challenges so we can skip those first slots

    when we validate vdfs with compressed values we get the uncompressed value as a result
    output_cache is used to store all these converted B objects to use as inputs for later vdfs
    """

    slot_iters, slots = uint64(0), 0
    output_cache: Dict[B, ClassgroupElement] = {}
    first_block = True
    prev_cc_challenge = None
    after_challenge_block = False
    slot_after_challenge_block = False
    deficit = 0
    challenge_included = False
    for idx, ssd in enumerate(segment.sub_slot_data):
        if idx < start_from:
            continue
        if ssd.is_challenge():
            challenge_included = True
            assert ssd.ip_iters
            prev_challenge_ip_iters = ssd.ip_iters
            deficit = constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1
        # sampled validate vdfs
        if after_challenge_block and not ssd.is_end_of_slot():
            deficit -= 1

        if ssd.is_challenge():
            # validate challenge block vdfs and pospace
            # we validate this in non sampled segments as well so we can validate the end of slot hashes
            assert cc_challenge is not None
            icc_challenge = _validate_challenge_sub_slot_data(
                constants,
                idx,
                segment.sub_slot_data,
                curr_difficulty,
                curr_ssi,
                cc_challenge,
                prev_cc_challenge,
                output_cache,
                sampled,
            )
            after_challenge_block = True
        elif sampled and after_challenge_block:
            # all vdfs from challenge block to end of segment
            # only if this is a sampled segment
            assert icc_challenge is not None
            if ssd.is_end_of_slot():
                validate_eos(cc_challenge, icc_challenge, constants, segment.sub_slot_data, idx, curr_ssi, output_cache)
            else:
                _validate_sub_slot_data(
                    constants,
                    idx,
                    segment.sub_slot_data,
                    curr_ssi,
                    cc_challenge,
                    prev_cc_challenge,
                    icc_challenge,
                    output_cache,
                )
        elif not after_challenge_block and not ssd.is_end_of_slot():
            # overflow blocks before challenge block
            # we always validate this so we can also validate the challenge block (we need the uncompressed inputs)
            assert icc_challenge is not None
            validate_overflow(
                cc_challenge, icc_challenge, constants, first_block, idx, output_cache, segment.sub_slot_data
            )
        if ssd.is_end_of_slot():
            # calculate the end of slot challenges
            if after_challenge_block:
                slot_after_challenge_block = True
            prev_cc_challenge = cc_challenge
            cc_challenge, icc_challenge = get_end_of_slot_hashes(
                cc_challenge,
                icc_challenge,
                curr_ssi,
                ses if (idx == 0 and start_from == 0) else None,
                segment,
                idx,
                deficit,
                prev_challenge_ip_iters,
            )
            slot_iters = uint64(slot_iters + curr_ssi)
            slots = uint64(slots + 1)
            if ses is not None and ses.new_sub_slot_iters is not None:
                curr_ssi = ses.new_sub_slot_iters
            if ses is not None and ses.new_difficulty is not None:
                curr_difficulty = ses.new_difficulty

        else:
            first_block = False
    assert icc_challenge is not None
    if not challenge_included:
        raise Exception("no challenge was found in segment")
    return prev_challenge_ip_iters, slot_iters, slots, cc_challenge, icc_challenge, slot_after_challenge_block


def get_end_of_slot_hashes(
    challenge: bytes32,
    icc_challenge: Optional[bytes32],
    curr_ssi: uint64,
    ses: Optional[SubEpochSummary],  # if end of sub epoch
    segment: SubEpochChallengeSegmentV2,
    index: int,
    prev_deficit: int,
    prev_challenge_ip_iters: uint64,
) -> Tuple[bytes32, Optional[bytes32]]:
    """
    get cc and icc hash  for end of slot
    """
    ssd = segment.sub_slot_data[index]
    icc_hash = None
    if ssd.icc_slot_end_output is not None:
        icc_iters = curr_ssi
        if index == 0:
            if segment.cc_slot_end_info is None:
                icc_iters = uint64(curr_ssi - prev_challenge_ip_iters)
            elif segment.prev_icc_ip_iters is not None:
                icc_iters = uint64(curr_ssi - segment.prev_icc_ip_iters)
        else:
            for sub_slot in reversed(segment.sub_slot_data[:index]):
                if sub_slot.is_challenge():
                    assert sub_slot.ip_iters
                    icc_iters = uint64(curr_ssi - sub_slot.ip_iters)
                    break
                if sub_slot.is_end_of_slot():
                    break
        if icc_challenge is not None:
            icc_hash = VDFInfo(icc_challenge, icc_iters, ssd.icc_slot_end_output).get_hash()
    assert ssd.cc_slot_end_output is not None
    cc_sub_slot = ChallengeChainSubSlot(
        VDFInfo(challenge, curr_ssi, ssd.cc_slot_end_output),
        icc_hash if prev_deficit == 0 else None,
        None if ses is None else ses.get_hash(),
        None if ses is None else ses.new_sub_slot_iters,
        None if ses is None else ses.new_difficulty,
    )
    log.debug(f"cc sub slot {cc_sub_slot} {cc_sub_slot.get_hash()} icc hash {icc_hash}")
    return cc_sub_slot.get_hash(), icc_hash


def validate_overflow(
    cc_sub_slot_hash: bytes32,
    icc_sub_slot_hash: bytes32,
    constants: ConsensusConstants,
    first_block: bool,
    idx: int,
    long_outputs: Dict[B, ClassgroupElement],
    sub_slots_data: List[SubSlotDataV2],
) -> None:
    """
    validate overflow block vdfs for blocks before the challenge block
    """
    ssd = sub_slots_data[idx]
    assert ssd.ip_iters is not None
    assert ssd.cc_infusion_point is not None
    assert ssd.cc_ip_vdf_output is not None
    prev_ssd = None
    cc_sp_iterations = ssd.ip_iters
    ip_input = ClassgroupElement.get_default_element()
    if not first_block:
        assert ssd.cc_ip_vdf_output is not None
        prev_ssd = sub_slots_data[idx - 1]
        if not ssd.cc_infusion_point.normalized_to_identity and not prev_ssd.is_end_of_slot():
            assert ssd.total_iters is not None
            assert prev_ssd.total_iters is not None
            assert prev_ssd.cc_ip_vdf_output is not None
            cc_sp_iterations = uint64(ssd.total_iters - prev_ssd.total_iters)
            ip_input = long_outputs[prev_ssd.cc_ip_vdf_output]
    valid, output = verify_compressed_vdf(
        constants, cc_sub_slot_hash, ip_input, ssd.cc_ip_vdf_output, ssd.cc_infusion_point, cc_sp_iterations
    )
    if not valid:
        raise Exception("failed cc infusion point vdf validation")
    long_outputs[ssd.cc_ip_vdf_output] = output
    if ssd.icc_infusion_point is not None:
        icc_ip_input = ClassgroupElement.get_default_element()
        if (
            prev_ssd is not None
            and prev_ssd.icc_infusion_point is not None
            and not prev_ssd.is_challenge()
            and not ssd.icc_infusion_point.normalized_to_identity
        ):
            if prev_ssd.icc_ip_vdf_output not in long_outputs:
                raise Exception("missing uncompressed output for vdf")
            icc_ip_input = long_outputs[prev_ssd.icc_ip_vdf_output]
        assert ssd.icc_ip_vdf_output is not None
        valid, output = verify_compressed_vdf(
            constants,
            icc_sub_slot_hash,
            icc_ip_input,
            ssd.icc_ip_vdf_output,
            ssd.icc_infusion_point,
            cc_sp_iterations,
        )
        if not valid:
            raise Exception("failed icc signage point vdf validation ")
        assert ssd.icc_ip_vdf_output
        long_outputs[ssd.icc_ip_vdf_output] = output

    return


def validate_eos(
    cc_sub_slot_hash: bytes32,
    icc_challenge: bytes32,
    constants: ConsensusConstants,
    sub_slots_data: List[SubSlotDataV2],
    idx: int,
    ssi: uint64,
    long_outputs: Dict[B, ClassgroupElement],
) -> None:
    """
    validates end of slot vdfs
    """
    cc_eos_iters = ssi
    cc_input = ClassgroupElement.get_default_element()
    ssd = sub_slots_data[idx]
    prev_ssd = sub_slots_data[idx - 1]
    if not prev_ssd.is_end_of_slot():
        assert ssd.cc_slot_end
        if not ssd.cc_slot_end.normalized_to_identity:
            assert prev_ssd.cc_ip_vdf_output
            assert prev_ssd.ip_iters
            cc_input = long_outputs[prev_ssd.cc_ip_vdf_output]
            cc_eos_iters = uint64(ssi - prev_ssd.ip_iters)
    assert ssd.cc_slot_end_output is not None
    cc_slot_end_info = VDFInfo(cc_sub_slot_hash, cc_eos_iters, ssd.cc_slot_end_output)
    assert ssd.cc_slot_end is not None
    if not ssd.cc_slot_end.is_valid(constants, cc_input, cc_slot_end_info):
        raise Exception(f"failed cc slot end validation  {cc_slot_end_info} \n input {cc_input}")
    icc_ip_input = ClassgroupElement.get_default_element()
    icc_eos_iters: uint64 = ssi
    if not prev_ssd.is_end_of_slot():
        if not ssd.cc_slot_end.normalized_to_identity:
            if prev_ssd.icc_ip_vdf_output is not None:
                icc_ip_input = long_outputs[prev_ssd.icc_ip_vdf_output]
            assert prev_ssd.ip_iters is not None
            icc_eos_iters = uint64(ssi - prev_ssd.ip_iters)
        else:
            for sub_slot in reversed(sub_slots_data[:idx]):
                if sub_slot.is_challenge():
                    assert sub_slot.ip_iters
                    icc_eos_iters = uint64(ssi - sub_slot.ip_iters)
                    break
                if sub_slot.is_end_of_slot():
                    break

    assert ssd.icc_slot_end_output
    icc_slot_end_info = VDFInfo(icc_challenge, icc_eos_iters, ssd.icc_slot_end_output)
    assert ssd.icc_slot_end
    if not ssd.icc_slot_end.is_valid(constants, icc_ip_input, icc_slot_end_info):
        raise Exception(f"failed icc slot end validation  {icc_slot_end_info} \n input {cc_input}")
    return


def _validate_challenge_sub_slot_data(
    constants: ConsensusConstants,
    ssd_idx: int,
    sub_slots: List[SubSlotDataV2],
    curr_difficulty: uint64,
    ssi: uint64,
    challenge: bytes32,
    prev_challenge: Optional[bytes32],
    long_outputs: Dict[B, ClassgroupElement],
    sampled: bool,
) -> bytes32:
    """
    validate vdfs from a challenge block
    """
    sub_slot_data = sub_slots[ssd_idx]
    prev_ssd = None
    if ssd_idx > 0:
        prev_ssd = sub_slots[ssd_idx - 1]
    assert sub_slot_data.signage_point_index is not None
    assert sub_slot_data.proof_of_space is not None
    assert sub_slot_data.ip_iters is not None
    sp_info = None
    sp_iters = calculate_sp_iters(constants, ssi, sub_slot_data.signage_point_index)
    if sp_iters != 0:
        assert sub_slot_data.cc_signage_point is not None
        is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
        sp_challenge = challenge
        assert sub_slot_data.cc_sp_vdf_output is not None
        cc_sp_input = ClassgroupElement.get_default_element()
        if is_overflow:
            assert prev_challenge is not None
            sp_challenge = prev_challenge
        if ssd_idx > 0 and not sub_slot_data.cc_signage_point.normalized_to_identity:
            tmp_input, sp_iters = sub_slot_data_vdf_info(ssd_idx, sub_slots, is_overflow, ssi, sp_iters)
            if isinstance(tmp_input, B):
                cc_sp_input = long_outputs[tmp_input]
            elif isinstance(tmp_input, ClassgroupElement):
                cc_sp_input = tmp_input
        sp_valid, sp_output = verify_compressed_vdf(
            constants,
            sp_challenge,
            cc_sp_input,
            sub_slot_data.cc_sp_vdf_output,
            sub_slot_data.cc_signage_point,
            sp_iters,
        )
        if not sp_valid:
            raise Exception(f"failed cc signage point vdf validation {ssd_idx}")
        long_outputs[sub_slot_data.cc_sp_vdf_output] = sp_output
        sp_iters = calculate_sp_iters(
            constants,
            ssi,
            sub_slot_data.signage_point_index,
        )
        assert sp_challenge is not None
        sp_info = VDFInfo(sp_challenge, sp_iters, sp_output)

    cc_ip_input = ClassgroupElement.get_default_element()
    ip_vdf_iters = sub_slot_data.ip_iters
    assert sub_slot_data.cc_infusion_point is not None
    if not sub_slot_data.cc_infusion_point.normalized_to_identity:
        if prev_ssd is not None and not prev_ssd.is_end_of_slot():
            assert prev_ssd.cc_ip_vdf_output
            cc_ip_input = long_outputs[prev_ssd.cc_ip_vdf_output]
            assert sub_slot_data is not None
            assert sub_slot_data.total_iters is not None
            assert prev_ssd.total_iters is not None
            ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
    assert ip_vdf_iters is not None
    assert sub_slot_data.cc_ip_vdf_output is not None
    ip_valid, ip_output = verify_compressed_vdf(
        constants,
        challenge,
        cc_ip_input,
        sub_slot_data.cc_ip_vdf_output,
        sub_slot_data.cc_infusion_point,
        ip_vdf_iters,
    )
    if not ip_valid:
        raise Exception(f"failed cc infusion point vdf validation {ssd_idx}")
    long_outputs[sub_slot_data.cc_ip_vdf_output] = ip_output

    pospace_challenge = challenge
    assert sub_slot_data.signage_point_index is not None
    if sampled:
        if is_overflow_block(constants, sub_slot_data.signage_point_index):
            assert prev_challenge is not None
            pospace_challenge = prev_challenge
        __validate_pospace(constants, sub_slot_data, curr_difficulty, pospace_challenge, ssi, long_outputs)
    cbi = ChallengeBlockInfo(
        sub_slot_data.proof_of_space,
        sp_info,
        sub_slot_data.cc_sp_signature,
        VDFInfo(challenge, sub_slot_data.ip_iters, ip_output),
    )
    return cbi.get_hash()


def _validate_sub_slot_data(
    constants: ConsensusConstants,
    sub_slot_idx: int,
    sub_slots: List[SubSlotDataV2],
    ssi: uint64,
    cc_challenge: bytes32,
    prev_cc_sub_slot_hash: Optional[bytes32],
    icc_challenge: bytes32,
    long_outputs: Dict[B, ClassgroupElement],
) -> None:
    """
    validate vdfs from a block
    """
    sub_slot_data = sub_slots[sub_slot_idx]
    prev_ssd = sub_slots[sub_slot_idx - 1]
    # find next end of slot
    assert sub_slot_data.signage_point_index is not None
    sp_iters = calculate_sp_iters(constants, ssi, sub_slot_data.signage_point_index)
    if sp_iters != 0:
        assert sub_slot_data.cc_signage_point is not None
        assert sub_slot_data.cc_sp_vdf_output is not None
        assert sub_slot_data.signage_point_index is not None
        cc_sp_input = ClassgroupElement.get_default_element()
        iterations = sp_iters
        challenge = cc_challenge
        is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
        if is_overflow:
            assert prev_cc_sub_slot_hash is not None
            challenge = prev_cc_sub_slot_hash
        if not sub_slot_data.cc_signage_point.normalized_to_identity:
            tmp_input, iterations = sub_slot_data_vdf_info(sub_slot_idx, sub_slots, is_overflow, ssi, sp_iters)
            if isinstance(tmp_input, B):
                cc_sp_input = long_outputs[tmp_input]
            elif isinstance(tmp_input, ClassgroupElement):
                cc_sp_input = tmp_input
        sp_valid, sp_output = verify_compressed_vdf(
            constants,
            challenge,
            cc_sp_input,
            sub_slot_data.cc_sp_vdf_output,
            sub_slot_data.cc_signage_point,
            iterations,
        )
        if not sp_valid:
            raise Exception("failed cc signage point vdf validation")
        assert sub_slot_data.cc_sp_vdf_output is not None
        long_outputs[sub_slot_data.cc_sp_vdf_output] = sp_output
    cc_ip_input = ClassgroupElement.get_default_element()
    assert sub_slot_data.ip_iters
    ip_vdf_iters = sub_slot_data.ip_iters
    assert sub_slot_data.cc_infusion_point is not None
    if not prev_ssd.is_end_of_slot() and not sub_slot_data.cc_infusion_point.normalized_to_identity:
        assert prev_ssd.cc_ip_vdf_output
        assert sub_slot_data.total_iters
        assert prev_ssd.total_iters
        cc_ip_input = long_outputs[prev_ssd.cc_ip_vdf_output]
        ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
    assert sub_slot_data.cc_ip_vdf_output is not None
    ip_valid, ip_output = verify_compressed_vdf(
        constants,
        cc_challenge,
        cc_ip_input,
        sub_slot_data.cc_ip_vdf_output,
        sub_slot_data.cc_infusion_point,
        ip_vdf_iters,
    )
    if not ip_valid:
        raise Exception(f"failed cc infusion point vdf validation {cc_challenge}")
    long_outputs[sub_slot_data.cc_ip_vdf_output] = ip_output

    if sub_slot_data.icc_infusion_point is not None:
        icc_ip_vdf_iters = sub_slot_data.ip_iters
        icc_ip_input = ClassgroupElement.get_default_element()
        assert prev_ssd is not None
        if not prev_ssd.is_end_of_slot():
            assert sub_slot_data.total_iters is not None
            assert prev_ssd.total_iters is not None
            icc_ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
            if not prev_ssd.is_challenge():
                assert prev_ssd.icc_ip_vdf_output is not None
                icc_ip_input = long_outputs[prev_ssd.icc_ip_vdf_output]
        assert sub_slot_data.icc_ip_vdf_output is not None
        assert icc_challenge is not None
        icc_ip_valid, icc_ip_output = verify_compressed_vdf(
            constants,
            icc_challenge,
            icc_ip_input,
            sub_slot_data.icc_ip_vdf_output,
            sub_slot_data.icc_infusion_point,
            icc_ip_vdf_iters,
        )
        if not icc_ip_valid:
            raise Exception("failed icc infusion point vdf validation")
        long_outputs[sub_slot_data.icc_ip_vdf_output] = icc_ip_output
    return


# find sp input and iterations
def sub_slot_data_vdf_info(
    sub_slot_idx: int,
    sub_slots: List[SubSlotDataV2],
    is_overflow: bool,
    ssi: uint64,
    sp_iters: uint64,
) -> Tuple[Union[B, ClassgroupElement], uint64]:
    sub_slot_data = sub_slots[sub_slot_idx]
    assert sub_slot_data.total_iters is not None
    assert sub_slot_data.signage_point_index is not None
    assert sub_slot_data.ip_iters
    sp_sub_slot_total_iters = uint128(sub_slot_data.total_iters - sub_slot_data.ip_iters)
    if is_overflow:
        sp_sub_slot_total_iters = uint128(sp_sub_slot_total_iters - ssi)
    sp_total_iters = uint128(sp_sub_slot_total_iters + sp_iters)
    ssd: Optional[SubSlotDataV2] = None
    slots_n = 1
    if is_overflow:
        slots_n = 2
    slots_seen = 0
    reached_start = False
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
        if ssd_idx == 0:
            reached_start = True
    assert ssd is not None
    if not ssd.is_end_of_slot() and not reached_start:
        assert ssd.total_iters
        if ssd.total_iters < sp_total_iters:
            assert ssd.cc_ip_vdf_output
            return ssd.cc_ip_vdf_output, uint64(sp_total_iters - ssd.total_iters)
    return ClassgroupElement.get_default_element(), sp_iters


def __validate_pospace(
    constants: ConsensusConstants,
    ssd: SubSlotDataV2,
    curr_diff: uint64,
    cc_sub_slot_hash: bytes32,
    ssi: uint64,
    long_outputs: Dict[B, ClassgroupElement],
) -> None:
    assert ssd.signage_point_index is not None
    sp_iters = calculate_sp_iters(constants, ssi, ssd.signage_point_index)
    if sp_iters == uint64(0):
        cc_sp_hash = cc_sub_slot_hash
    else:
        assert ssd.cc_sp_vdf_output
        cc_sp_hash = long_outputs[ssd.cc_sp_vdf_output].get_hash()

    # validate proof of space
    assert ssd.proof_of_space is not None
    q_str = ssd.proof_of_space.verify_and_get_quality_string(
        constants,
        cc_sub_slot_hash,
        cc_sp_hash,
    )
    if q_str is None:
        raise Exception("could not validate proof of space")

    iterations = calculate_iterations_quality(
        constants.DIFFICULTY_CONSTANT_FACTOR,
        q_str,
        ssd.proof_of_space.size,
        curr_diff,
        cc_sp_hash,
    )

    if iterations >= calculate_sp_interval_iters(constants, ssi):
        raise Exception("invalid required iters for proof of space")

    return


def __get_rc_sub_slot_hash(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegmentV2,
    summaries: List[SubEpochSummary],
    prev_ssi: uint64,
) -> Tuple[bytes32, int]:
    slots = segment.sub_slot_data
    ses = summaries[uint32(segment.sub_epoch_n - 1)]
    # find first block sub epoch
    last_slot_idx = None
    first_block_in_se = None
    for idx, curr in enumerate(segment.sub_slot_data):
        if not curr.is_end_of_slot():
            last_slot_idx = idx - 1
            first_block_in_se = curr
            break

    if last_slot_idx is None or first_block_in_se is None:
        raise Exception("could not find first block in sub epoch")

    challenge_slot = slots[last_slot_idx]
    new_diff = ses.new_difficulty if last_slot_idx == 0 else None
    new_ssi = ses.new_sub_slot_iters if last_slot_idx == 0 else None
    ses_hash = ses.get_hash() if last_slot_idx == 0 else None

    assert segment.cc_slot_end_info is not None
    assert segment.rc_slot_end_info is not None

    icc_iters = prev_ssi
    if segment.prev_icc_ip_iters is not None:
        icc_iters = uint64(prev_ssi - segment.prev_icc_ip_iters)

    icc_info_hash = None
    if challenge_slot.icc_slot_end_output is not None:
        assert segment.icc_sub_slot_hash
        icc_info_hash = VDFInfo(segment.icc_sub_slot_hash, icc_iters, challenge_slot.icc_slot_end_output).get_hash()

    cc_sub_slot = ChallengeChainSubSlot(segment.cc_slot_end_info, icc_info_hash, ses_hash, new_ssi, new_diff)
    rc_sub_slot = RewardChainSubSlot(
        segment.rc_slot_end_info,
        cc_sub_slot.get_hash(),
        icc_info_hash,
        constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK,
    )

    log.debug(f"sub epoch start, cc sub slot {cc_sub_slot}")
    log.debug(f"sub epoch start, rc sub slot {rc_sub_slot}")
    return rc_sub_slot.get_hash(), last_slot_idx


def _get_curr_diff_ssi(
    constants: ConsensusConstants, idx: int, summaries: List[SubEpochSummary]
) -> Tuple[uint64, uint64]:
    curr_difficulty = constants.DIFFICULTY_STARTING
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    if idx == 0:
        # genesis
        return curr_difficulty, curr_ssi
    for ses in reversed(summaries[0 : idx - 1]):
        if ses.new_sub_slot_iters is not None:
            curr_ssi = ses.new_sub_slot_iters
        if ses.new_difficulty is not None:
            curr_difficulty = ses.new_difficulty
            break

    return curr_difficulty, curr_ssi


def _get_last_ses(
    constants: ConsensusConstants, recent_reward_chain: List[HeaderBlock]
) -> Tuple[Optional[bytes32], uint32, uint128]:
    """
    find the last sub epoch summary in the chain
    return ses, ses_block height, ses_block weight
    """
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
    raise Exception("did not find sub epoch summary in recent chain")


def preprocess_sub_epoch_sampling(rng: random.Random, sub_epoch_weight_list: List[uint128]) -> Dict[int, bool]:
    total_weight = sub_epoch_weight_list[-1]
    last_l_weight = uint128(sub_epoch_weight_list[-1] - sub_epoch_weight_list[-3])
    log.debug(f"total weight {total_weight} prev weight {sub_epoch_weight_list[-2]}")
    weight_to_check = _get_weights_for_sampling(rng, total_weight, last_l_weight)
    sampled_sub_epochs: Dict[int, bool] = {}
    for idx in range(1, len(sub_epoch_weight_list)):
        if _sample_sub_epoch(sub_epoch_weight_list[idx - 1], sub_epoch_weight_list[idx], weight_to_check):
            sampled_sub_epochs[idx - 1] = True
            if len(sampled_sub_epochs) == WeightProofHandlerV2.MAX_SAMPLES:
                break
    return sampled_sub_epochs


async def get_recent_chain(blockchain: BlockchainInterface, tip_height: uint32) -> Optional[List[HeaderBlock]]:
    """
    returns the latest chain part to attach to the WP,  all the blocks since the previous to last ses
    """
    recent_chain: List[HeaderBlock] = []
    ses_heights = blockchain.get_ses_heights()
    min_height = 0
    count_ses = 0
    for ses_height in reversed(ses_heights):
        if ses_height <= tip_height:
            count_ses += 1
        if count_ses == WeightProofHandlerV2.SUB_EPOCHS_RECENT_CHAIN:
            min_height = ses_height - 1
            break
    log.info(f"start {min_height} end {tip_height}")
    headers = await blockchain.get_header_blocks_in_range(min_height, tip_height, tx_filter=False)
    block_records = await blockchain.get_block_records_in_range(min_height, tip_height)
    ses_count = 0
    curr_height = tip_height
    blocks_n = 0
    while ses_count < WeightProofHandlerV2.SUB_EPOCHS_RECENT_CHAIN:
        if curr_height == 0:
            break
        # add to needed reward chain recent blocks
        header_hash = blockchain.height_to_hash(curr_height)
        assert header_hash
        header_block = headers[header_hash]
        if header_block is None:
            log.error("creating recent chain failed")
            return None
        recent_chain.insert(0, header_block)
        if block_records[header_block.header_hash].sub_epoch_summary_included:
            ses_count += 1
        curr_height = uint32(curr_height - 1)
        blocks_n += 1

    header_hash = blockchain.height_to_hash(curr_height)
    assert header_hash
    recent_chain.insert(0, headers[header_hash])

    log.debug(
        f"recent chain, "
        f"start: {recent_chain[0].reward_chain_block.height} "
        f"end:  {recent_chain[-1].reward_chain_block.height} "
    )
    return recent_chain


def blue_boxed_end_of_slot(sub_slot: EndOfSubSlotBundle) -> bool:
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
            if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                return True
        else:
            return True
    return False


def _sample_sub_epoch(
    start_of_epoch_weight: uint128,
    end_of_epoch_weight: uint128,
    weight_to_check: Optional[List[uint128]],
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


def _validate_recent_blocks(
    constants_dict: Dict[str, Any], recent_chain_bytes: bytes, summaries_bytes: List[bytes]
) -> List[bytes]:
    """
    validate pospace for blocks after the first two slots, full validation for last 100 blocks
    returns the result and the list of blocks records as bytes
    """

    constants, summaries = bytes_to_vars(constants_dict, summaries_bytes)
    recent_chain: RecentChainData = RecentChainData.from_bytes(recent_chain_bytes)
    full_validation = 100
    if constants.LAST_BLOCKS_FULL_VALIDATION is not None:
        full_validation = constants.LAST_BLOCKS_FULL_VALIDATION
    count = 0
    for idx, curr in enumerate(recent_chain.recent_chain_data):
        if len(curr.finished_sub_slots) > 0:
            for slot in curr.finished_sub_slots:
                if slot.challenge_chain.subepoch_summary_hash is not None:
                    count += 1

    if count != WeightProofHandlerV2.SUB_EPOCHS_RECENT_CHAIN:
        raise Exception(f"wrong ses count in recent chain. {count}")
    # find ses previous to first block in recent blocks
    ses_idx: int = len(summaries) - count
    ssi: uint64 = constants.SUB_SLOT_ITERS_STARTING
    diff: uint64 = constants.DIFFICULTY_STARTING
    # find ssi diff up to first block
    for summary in summaries[:ses_idx]:
        if summary.new_sub_slot_iters is not None:
            ssi = summary.new_sub_slot_iters
        if summary.new_difficulty is not None:
            diff = summary.new_difficulty
    sub_blocks = BlockCache({})
    ses_blocks, sub_slots, tx_blocks = 0, 0, 0
    challenge, prev_challenge = None, None
    tip_height = recent_chain.recent_chain_data[-1].height
    prev_block_record = None
    deficit: uint8 = uint8(0)
    for idx, block in enumerate(recent_chain.recent_chain_data[1:]):
        required_iters: Optional[uint64] = uint64(0)
        overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
        ses = False
        height = block.height
        for sub_slot in block.finished_sub_slots:
            prev_challenge = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
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
            log.debug(f"wp, validate block {block.height}")
            if sub_slots > 2 and tx_blocks > 11 and (tip_height - block.height < full_validation):
                required_iters, error = validate_finished_header_block(
                    constants, sub_blocks, block, False, diff, ssi, ses_blocks > 2
                )
                if error is not None:
                    raise Exception(f"block {block.header_hash} failed validation {error}")

            else:
                required_iters = _validate_pospace_recent_chain(
                    constants, block, challenge, diff, overflow, prev_challenge, ssi
                )
            assert required_iters
        if prev_block_record is None:
            # this is the first ses block in the recent chain
            if ses is False:
                raise Exception("second block in recent chain must have sub epoch summary")
            if not (overflow and deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK):
                deficit = uint8(deficit - uint8(1))
        else:
            deficit = calculate_deficit(constants, height, prev_block_record, overflow, len(block.finished_sub_slots))

        curr_block_ses = None if not ses else summaries[ses_idx - 1]
        assert required_iters
        block_record = header_block_to_sub_block_record(
            constants, required_iters, block, ssi, overflow, deficit, height, curr_block_ses
        )
        log.debug(f"add block {block_record.height} to tmp sub blocks")
        sub_blocks.add_block_record(block_record)

        if block.first_in_sub_slot:
            sub_slots += 1
        if block.is_transaction_block:
            tx_blocks += 1
        if ses:
            ses_blocks += 1
        prev_block_record = block_record

    return [bytes(sub) for sub in sub_blocks._block_records.values()]


def _validate_pospace_recent_chain(
    constants: ConsensusConstants,
    block: HeaderBlock,
    challenge: bytes32,
    diff: uint64,
    overflow: bool,
    prev_challenge: bytes32,
    ssi: uint64,
) -> uint64:
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
        raise Exception(f"could not verify proof of space block {block.height} {overflow}")
    required_iters = calculate_iterations_quality(
        constants.DIFFICULTY_CONSTANT_FACTOR,
        q_str,
        block.reward_chain_block.proof_of_space.size,
        diff,
        cc_sp_hash,
    )
    if required_iters >= calculate_sp_interval_iters(constants, ssi):
        raise Exception("invalid iters for proof of space")
    return required_iters


def vars_to_bytes(
    constants: ConsensusConstants, summaries: List[SubEpochSummary], weight_proof: WeightProofV2
) -> Tuple[Dict[str, Any], List[bytes], bytes]:
    constants_dict = recurse_jsonify(dataclasses.asdict(constants))
    wp_recent_chain_bytes = bytes(RecentChainData(weight_proof.recent_chain_data))
    summary_bytes = []
    for summary in summaries:
        summary_bytes.append(bytes(summary))
    return constants_dict, summary_bytes, wp_recent_chain_bytes


def bytes_to_vars(
    constants_dict: Dict[str, Any], summaries_bytes: List[bytes]
) -> Tuple[ConsensusConstants, List[SubEpochSummary]]:
    summaries = []
    for summary in summaries_bytes:
        summaries.append(SubEpochSummary.from_bytes(summary))
    constants = dataclass_from_dict(ConsensusConstants, constants_dict)
    return constants, summaries


async def validate_weight_proof_no_fork_point(
    constants: ConsensusConstants, weight_proof: WeightProofV2, seed: bytes32, skip_segments: bool = False
) -> Tuple[bool, List[SubEpochSummary], List[BlockRecord]]:
    if len(weight_proof.sub_epoch_segments) > WeightProofHandlerV2.MAX_SAMPLES:
        log.error("weight proof has a wrong number of samples")
        return False, [], []

    peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
    log.info(f"validate weight proof peak height {peak_height}")

    result = _validate_sub_epoch_summaries(constants, weight_proof)
    if result is None:
        log.error("weight proof failed sub epoch data validation")
        return False, [], []
    summaries, sub_epoch_weight_list = result
    rng = random.Random(seed)
    sampled_sub_epochs = preprocess_sub_epoch_sampling(rng, sub_epoch_weight_list)
    constants_dict, summary_bytes, wp_recent_chain_bytes = vars_to_bytes(constants, summaries, weight_proof)

    with ProcessPoolExecutor() as executor:
        recent_blocks_validation_task = executor.submit(
            _validate_recent_blocks, constants_dict, wp_recent_chain_bytes, summary_bytes
        )
        if not skip_segments:
            valid, sub_epochs = _validate_sub_epoch_segments(
                constants_dict, rng, weight_proof.sub_epoch_segments, summary_bytes, executor
            )
            if not valid:
                log.error("failed validating weight proof sub epoch segments")
                return False, [], []

    # check that all sampled sub epochs are in the WP
    for sub_epoch_n in sub_epochs:
        if sub_epoch_n in sampled_sub_epochs:
            del sampled_sub_epochs[sub_epoch_n]
    if len(sampled_sub_epochs) > 0:
        log.error("failed weight proof sub epoch sample validation")
        return False, [], []

    if recent_blocks_validation_task.exception() is not None:
        log.error(f"error validating recent chain {recent_blocks_validation_task.exception()}")
        return False, [], []

    records_bytes = recent_blocks_validation_task.result()
    return True, summaries, [BlockRecord.from_bytes(b) for b in records_bytes]
