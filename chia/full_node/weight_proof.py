from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
import pathlib
import random
import tempfile
from concurrent.futures.process import ProcessPoolExecutor
from multiprocessing.context import BaseContext
from typing import IO, Dict, List, Optional, Tuple

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import header_block_to_sub_block_record
from chia.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_iterations_quality,
    calculate_sp_iters,
    is_overflow_block,
)
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.proof_of_space import verify_and_get_quality_string
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof, validate_vdf
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import (
    RecentChainData,
    SubEpochChallengeSegment,
    SubEpochData,
    SubEpochSegments,
    SubSlotData,
    WeightProof,
)
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.misc import to_batches
from chia.util.setproctitle import getproctitle, setproctitle

log = logging.getLogger(__name__)


def _create_shutdown_file() -> IO[bytes]:
    return tempfile.NamedTemporaryFile(prefix="chia_full_node_weight_proof_handler_executor_shutdown_trigger")


class WeightProofHandler:
    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 20

    def __init__(
        self,
        constants: ConsensusConstants,
        blockchain: BlockchainInterface,
        multiprocessing_context: Optional[BaseContext] = None,
    ):
        self.tip: Optional[bytes32] = None
        self.proof: Optional[WeightProof] = None
        self.constants = constants
        self.blockchain = blockchain
        self.lock = asyncio.Lock()
        self._num_processes = 4
        self.multiprocessing_context = multiprocessing_context

    async def get_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            log.error("unknown tip")
            return None

        if tip_rec.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            log.debug("chain to short for weight proof")
            return None

        async with self.lock:
            if self.proof is not None:
                if self.proof.recent_chain_data[-1].header_hash == tip:
                    return self.proof
            wp = await self._create_proof_of_weight(tip)
            if wp is None:
                return None
            self.proof = wp
            self.tip = tip
            return wp

    def get_sub_epoch_data(self, tip_height: uint32, summary_heights: List[uint32]) -> List[SubEpochData]:
        sub_epoch_data: List[SubEpochData] = []
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            if ses_height > tip_height:
                break
            ses = self.blockchain.get_ses(ses_height)
            log.debug("handle sub epoch summary %s at height: %s ses %s", sub_epoch_n, ses_height, ses)
            sub_epoch_data.append(_create_sub_epoch_data(ses))
        return sub_epoch_data

    async def _create_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        """
        Creates a weight proof object
        """
        assert self.blockchain is not None
        sub_epoch_segments: List[SubEpochChallengeSegment] = []
        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            log.error("failed not tip in cache")
            return None
        log.info(f"create weight proof peak {tip} {tip_rec.height}")
        recent_chain = await self._get_recent_chain(tip_rec.height)
        if recent_chain is None:
            return None

        summary_heights = self.blockchain.get_ses_heights()
        zero_hash = self.blockchain.height_to_hash(uint32(0))
        assert zero_hash is not None
        prev_ses_block = await self.blockchain.get_block_record_from_db(zero_hash)
        if prev_ses_block is None:
            return None
        sub_epoch_data = self.get_sub_epoch_data(tip_rec.height, summary_heights)
        # use second to last ses as seed
        seed = self.get_seed_for_proof(summary_heights, tip_rec.height)
        rng = random.Random(seed)
        weight_to_check = _get_weights_for_sampling(rng, tip_rec.weight, recent_chain)
        sample_n = 0
        ses_blocks = await self.blockchain.get_block_records_at(summary_heights)
        if ses_blocks is None:
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

            if _sample_sub_epoch(prev_ses_block.weight, ses_block.weight, weight_to_check):
                sample_n += 1
                segments = await self.blockchain.get_sub_epoch_challenge_segments(ses_block.header_hash)
                if segments is None:
                    segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(sub_epoch_n))
                    if segments is None:
                        log.error(
                            f"failed while building segments for sub epoch {sub_epoch_n}, ses height {ses_height} "
                        )
                        return None
                    await self.blockchain.persist_sub_epoch_challenge_segments(ses_block.header_hash, segments)
                sub_epoch_segments.extend(segments)
            prev_ses_block = ses_block
        log.debug(f"sub_epochs: {len(sub_epoch_data)}")
        return WeightProof(sub_epoch_data, sub_epoch_segments, recent_chain)

    def get_seed_for_proof(self, summary_heights: List[uint32], tip_height: uint32) -> bytes32:
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
            header_hash = self.blockchain.height_to_hash(curr_height)
            assert header_hash is not None
            header_block = headers[header_hash]
            block_rec = blocks[header_block.header_hash]
            if header_block is None:
                log.error("creating recent chain failed")
                return None
            recent_chain.insert(0, header_block)
            if block_rec.sub_epoch_summary_included:
                ses_count += 1
            curr_height = uint32(curr_height - 1)
            blocks_n += 1

        header_hash = self.blockchain.height_to_hash(curr_height)
        assert header_hash is not None
        header_block = headers[header_hash]
        recent_chain.insert(0, header_block)

        log.info(
            f"recent chain, "
            f"start: {recent_chain[0].reward_chain_block.height} "
            f"end:  {recent_chain[-1].reward_chain_block.height} "
        )
        return recent_chain

    async def create_prev_sub_epoch_segments(self) -> None:
        log.debug("create prev sub_epoch_segments")
        heights = self.blockchain.get_ses_heights()
        if len(heights) < 3:
            return None
        count = len(heights) - 2
        ses_sub_block = self.blockchain.height_to_block_record(heights[-2])
        prev_ses_sub_block = self.blockchain.height_to_block_record(heights[-3])
        assert prev_ses_sub_block.sub_epoch_summary_included is not None
        segments = await self.__create_sub_epoch_segments(ses_sub_block, prev_ses_sub_block, uint32(count))
        assert segments is not None
        await self.blockchain.persist_sub_epoch_challenge_segments(ses_sub_block.header_hash, segments)
        log.debug("sub_epoch_segments done")
        return None

    async def create_sub_epoch_segments(self) -> None:
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
        h_hash: Optional[bytes32] = self.blockchain.height_to_hash(uint32(0))
        if h_hash is None:
            return None
        prev_ses_block: Optional[BlockRecord] = await self.blockchain.get_block_record_from_db(h_hash)
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

    async def __create_persist_segment(
        self, prev_ses_block: BlockRecord, ses_block: BlockRecord, ses_height: uint32, sub_epoch_n: int
    ) -> None:
        segments = await self.blockchain.get_sub_epoch_challenge_segments(ses_block.header_hash)
        if segments is None:
            segments = await self.__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(sub_epoch_n))
            if segments is None:
                log.error(f"failed while building segments for sub epoch {sub_epoch_n}, ses height {ses_height} ")
                return None
            await self.blockchain.persist_sub_epoch_challenge_segments(ses_block.header_hash, segments)

    async def __create_sub_epoch_segments(
        self, ses_block: BlockRecord, se_start: BlockRecord, sub_epoch_n: uint32
    ) -> Optional[List[SubEpochChallengeSegment]]:
        segments: List[SubEpochChallengeSegment] = []
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
                height = uint32(height + 1)
            header_hash = self.blockchain.height_to_hash(height)
            assert header_hash is not None
            curr = header_blocks[header_hash]
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
            header_hash = self.blockchain.height_to_hash(uint32(curr_rec.height - 1))
            assert header_hash is not None
            curr_rec = blocks[header_hash]
        return curr_rec.height

    async def _create_challenge_segment(
        self,
        header_block: HeaderBlock,
        sub_epoch_n: uint32,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
        first_segment_in_sub_epoch: bool,
    ) -> Tuple[Optional[SubEpochChallengeSegment], uint32]:
        assert self.blockchain is not None
        sub_slots: List[SubSlotData] = []
        log.debug(f"create challenge segment block {header_block.header_hash} block height {header_block.height} ")
        # VDFs from sub slots before challenge block
        first_sub_slots, first_rc_end_of_slot_vdf = await self.__first_sub_slot_vdfs(
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
            return (
                SubEpochChallengeSegment(sub_epoch_n, sub_slots, first_rc_end_of_slot_vdf),
                end_height,
            )
        return SubEpochChallengeSegment(sub_epoch_n, sub_slots, None), end_height

    # returns a challenge chain vdf from slot start to signage point
    async def __first_sub_slot_vdfs(
        self,
        header_block: HeaderBlock,
        header_blocks: Dict[bytes32, HeaderBlock],
        blocks: Dict[bytes32, BlockRecord],
        first_in_sub_epoch: bool,
    ) -> Tuple[Optional[List[SubSlotData]], Optional[VDFInfo]]:
        # combine cc vdfs of all reward blocks from the start of the sub slot to end
        header_block_sub_rec = blocks[header_block.header_hash]
        # find slot start
        curr_sub_rec = header_block_sub_rec
        first_rc_end_of_slot_vdf = None
        if first_in_sub_epoch and curr_sub_rec.height > 0:
            while not curr_sub_rec.sub_epoch_summary_included:
                curr_sub_rec = blocks[curr_sub_rec.prev_hash]
            first_rc_end_of_slot_vdf = self.first_rc_end_of_slot_vdf(header_block, blocks, header_blocks)
        else:
            if header_block_sub_rec.overflow and header_block_sub_rec.first_in_sub_slot:
                sub_slots_num = 2
                while sub_slots_num > 0 and curr_sub_rec.height > 0:
                    if curr_sub_rec.first_in_sub_slot:
                        assert curr_sub_rec.finished_challenge_slot_hashes is not None
                        sub_slots_num -= len(curr_sub_rec.finished_challenge_slot_hashes)
                    curr_sub_rec = blocks[curr_sub_rec.prev_hash]
            else:
                while not curr_sub_rec.first_in_sub_slot and curr_sub_rec.height > 0:
                    curr_sub_rec = blocks[curr_sub_rec.prev_hash]

        curr = header_blocks[curr_sub_rec.header_hash]
        sub_slots_data: List[SubSlotData] = []
        tmp_sub_slots_data: List[SubSlotData] = []
        while curr.height < header_block.height:
            if curr is None:
                log.error("failed fetching block")
                return None, None
            if curr.first_in_sub_slot:
                # if not blue boxed
                if not blue_boxed_end_of_slot(curr.finished_sub_slots[0]):
                    sub_slots_data.extend(tmp_sub_slots_data)

                for idx, sub_slot in enumerate(curr.finished_sub_slots):
                    curr_icc_info = None
                    if sub_slot.infused_challenge_chain is not None:
                        curr_icc_info = sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
                    sub_slots_data.append(handle_finished_slots(sub_slot, curr_icc_info))
                tmp_sub_slots_data = []
            ssd = SubSlotData(
                None,
                None,
                None,
                None,
                None,
                uint8(curr.reward_chain_block.signage_point_index),
                None,
                None,
                None,
                None,
                curr.reward_chain_block.challenge_chain_ip_vdf,
                curr.reward_chain_block.infused_challenge_chain_ip_vdf,
                curr.total_iters,
            )
            tmp_sub_slots_data.append(ssd)
            header_hash = self.blockchain.height_to_hash(uint32(curr.height + 1))
            assert header_hash is not None
            curr = header_blocks[header_hash]

        if len(tmp_sub_slots_data) > 0:
            sub_slots_data.extend(tmp_sub_slots_data)

        for idx, sub_slot in enumerate(header_block.finished_sub_slots):
            curr_icc_info = None
            if sub_slot.infused_challenge_chain is not None:
                curr_icc_info = sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
            sub_slots_data.append(handle_finished_slots(sub_slot, curr_icc_info))

        return sub_slots_data, first_rc_end_of_slot_vdf

    def first_rc_end_of_slot_vdf(
        self,
        header_block: HeaderBlock,
        blocks: Dict[bytes32, BlockRecord],
        header_blocks: Dict[bytes32, HeaderBlock],
    ) -> Optional[VDFInfo]:
        curr = blocks[header_block.header_hash]
        while curr.height > 0 and not curr.sub_epoch_summary_included:
            curr = blocks[curr.prev_hash]
        return header_blocks[curr.header_hash].finished_sub_slots[-1].reward_chain.end_of_slot_vdf

    async def __slot_end_vdf(
        self, start_height: uint32, header_blocks: Dict[bytes32, HeaderBlock], blocks: Dict[bytes32, BlockRecord]
    ) -> Tuple[Optional[List[SubSlotData]], uint32]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        log.debug(f"slot end vdf start height {start_height}")
        header_hash = self.blockchain.height_to_hash(start_height)
        assert header_hash is not None
        curr = header_blocks[header_hash]
        curr_header_hash = curr.header_hash
        sub_slots_data: List[SubSlotData] = []
        tmp_sub_slots_data: List[SubSlotData] = []
        while not blocks[curr_header_hash].is_challenge_block(self.constants):
            if curr.first_in_sub_slot:
                sub_slots_data.extend(tmp_sub_slots_data)

                curr_prev_header_hash = curr.prev_header_hash
                # add collected vdfs
                for idx, sub_slot in enumerate(curr.finished_sub_slots):
                    prev_rec = blocks[curr_prev_header_hash]
                    eos_vdf_iters = prev_rec.sub_slot_iters
                    if idx == 0:
                        eos_vdf_iters = uint64(prev_rec.sub_slot_iters - prev_rec.ip_iters(self.constants))
                    sub_slots_data.append(handle_end_of_slot(sub_slot, eos_vdf_iters))
                tmp_sub_slots_data = []
            tmp_sub_slots_data.append(self.handle_block_vdfs(curr, blocks))
            header_hash = self.blockchain.height_to_hash(uint32(curr.height + 1))
            assert header_hash is not None
            curr = header_blocks[header_hash]
            curr_header_hash = curr.header_hash

        if len(tmp_sub_slots_data) > 0:
            sub_slots_data.extend(tmp_sub_slots_data)
        log.debug(f"slot end vdf end height {curr.height} slots {len(sub_slots_data)} ")
        return sub_slots_data, curr.height

    def handle_block_vdfs(self, curr: HeaderBlock, blocks: Dict[bytes32, BlockRecord]) -> SubSlotData:
        cc_sp_proof = None
        icc_ip_proof = None
        cc_sp_info = None
        icc_ip_info = None
        block_record = blocks[curr.header_hash]
        if curr.infused_challenge_chain_ip_proof is not None:
            assert curr.reward_chain_block.infused_challenge_chain_ip_vdf
            icc_ip_proof = curr.infused_challenge_chain_ip_proof
            icc_ip_info = curr.reward_chain_block.infused_challenge_chain_ip_vdf
        if curr.challenge_chain_sp_proof is not None:
            assert curr.reward_chain_block.challenge_chain_sp_vdf
            cc_sp_vdf_info = curr.reward_chain_block.challenge_chain_sp_vdf
            if not curr.challenge_chain_sp_proof.normalized_to_identity:
                (_, _, _, _, cc_vdf_iters, _) = get_signage_point_vdf_info(
                    self.constants,
                    curr.finished_sub_slots,
                    block_record.overflow,
                    None if curr.height == 0 else blocks[curr.prev_header_hash],
                    BlockCache(blocks),
                    block_record.sp_total_iters(self.constants),
                    block_record.sp_iters(self.constants),
                )
                cc_sp_vdf_info = VDFInfo(
                    curr.reward_chain_block.challenge_chain_sp_vdf.challenge,
                    cc_vdf_iters,
                    curr.reward_chain_block.challenge_chain_sp_vdf.output,
                )
            cc_sp_proof = curr.challenge_chain_sp_proof
            cc_sp_info = cc_sp_vdf_info
        return SubSlotData(
            None,
            cc_sp_proof,
            curr.challenge_chain_ip_proof,
            icc_ip_proof,
            cc_sp_info,
            uint8(curr.reward_chain_block.signage_point_index),
            None,
            None,
            None,
            None,
            curr.reward_chain_block.challenge_chain_ip_vdf,
            icc_ip_info,
            curr.total_iters,
        )

    def validate_weight_proof_single_proc(self, weight_proof: WeightProof) -> Tuple[bool, uint32]:
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)

        peak_height = uint32(weight_proof.recent_chain_data[-1].reward_chain_block.height)
        log.info(f"validate weight proof peak height {peak_height}")
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.warning("weight proof failed sub epoch data validation")
            return False, uint32(0)
        summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(summaries, weight_proof)
        log.info("validate sub epoch challenge segments")
        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        assert sub_epoch_weight_list is not None
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error("failed weight proof sub epoch sample validation")
            return False, uint32(0)

        if _validate_sub_epoch_segments(self.constants, rng, wp_segment_bytes, summary_bytes, peak_height) is None:
            return False, uint32(0)
        log.info("validate weight proof recent blocks")
        success, _ = validate_recent_blocks(self.constants, wp_recent_chain_bytes, summary_bytes)
        if not success:
            return False, uint32(0)
        fork_point, _ = self.get_fork_point(summaries)
        return True, fork_point

    async def validate_weight_proof(self, weight_proof: WeightProof) -> Tuple[bool, uint32, List[SubEpochSummary]]:
        assert self.blockchain is not None
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0), []

        # timing reference: start
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        await asyncio.sleep(0)  # break up otherwise multi-second sync code
        # timing reference: 1 second
        if summaries is None or sub_epoch_weight_list is None:
            log.error("weight proof failed sub epoch data validation")
            return False, uint32(0), []

        fork_point, ses_fork_idx = self.get_fork_point(summaries)
        # timing reference: 1 second
        # TODO: Consider implementing an async polling closer for the executor.
        with ProcessPoolExecutor(
            max_workers=self._num_processes,
            mp_context=self.multiprocessing_context,
            initializer=setproctitle,
            initargs=(f"{getproctitle()}_weight_proof_worker",),
        ) as executor:
            # The shutdown file manager must be inside of the executor manager so that
            # we request the workers close prior to waiting for them to close.
            with _create_shutdown_file() as shutdown_file:
                task = asyncio.create_task(
                    validate_weight_proof_inner(
                        self.constants,
                        executor,
                        shutdown_file.name,
                        self._num_processes,
                        weight_proof,
                        summaries,
                        sub_epoch_weight_list,
                        False,
                        ses_fork_idx,
                    )
                )
                valid, _ = await task
        return valid, fork_point, summaries

    def get_fork_point(self, received_summaries: List[SubEpochSummary]) -> Tuple[uint32, int]:
        # returns the fork height and ses index
        # iterate through sub epoch summaries to find fork point
        fork_point_index = 0
        ses_heights = self.blockchain.get_ses_heights()
        for idx, summary_height in enumerate(ses_heights):
            log.debug(f"check summary {idx} height {summary_height}")
            local_ses = self.blockchain.get_ses(summary_height)
            if idx == len(received_summaries) - 1:
                # end of wp summaries, local chain is longer or equal to wp chain
                break
            if local_ses is None or local_ses.get_hash() != received_summaries[idx].get_hash():
                break
            fork_point_index = idx

        if fork_point_index <= 2:
            # Two summeries can have different blocks and still be identical
            # This gets resolved after one full sub epoch
            return uint32(0), 0

        return ses_heights[fork_point_index - 2], fork_point_index


def _get_weights_for_sampling(
    rng: random.Random, total_weight: uint128, recent_chain: List[HeaderBlock]
) -> Optional[List[uint128]]:
    weight_to_check = []
    last_l_weight = recent_chain[-1].reward_chain_block.weight - recent_chain[0].reward_chain_block.weight
    delta = last_l_weight / total_weight
    prob_of_adv_succeeding = 1 - math.log(WeightProofHandler.C, delta)
    if prob_of_adv_succeeding <= 0:
        return None
    queries = -WeightProofHandler.LAMBDA_L * math.log(2, prob_of_adv_succeeding)
    for i in range(int(queries) + 1):
        u = rng.random()
        q = 1 - delta**u
        # todo check division and type conversions
        weight = q * float(total_weight)
        weight_to_check.append(uint128(int(weight)))
    weight_to_check.sort()
    return weight_to_check


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
    sub_blocks: Dict[bytes32, BlockRecord],
) -> SubSlotData:
    (_, _, _, _, cc_vdf_iters, _) = get_signage_point_vdf_info(
        constants,
        header_block.finished_sub_slots,
        block_rec.overflow,
        None if header_block.height == 0 else sub_blocks[header_block.prev_header_hash],
        BlockCache(sub_blocks),
        block_rec.sp_total_iters(constants),
        block_rec.sp_iters(constants),
    )

    cc_sp_info = None
    if header_block.reward_chain_block.challenge_chain_sp_vdf:
        cc_sp_info = header_block.reward_chain_block.challenge_chain_sp_vdf
        assert header_block.challenge_chain_sp_proof
        if not header_block.challenge_chain_sp_proof.normalized_to_identity:
            cc_sp_info = VDFInfo(
                header_block.reward_chain_block.challenge_chain_sp_vdf.challenge,
                cc_vdf_iters,
                header_block.reward_chain_block.challenge_chain_sp_vdf.output,
            )
    ssd = SubSlotData(
        header_block.reward_chain_block.proof_of_space,
        header_block.challenge_chain_sp_proof,
        header_block.challenge_chain_ip_proof,
        None,
        cc_sp_info,
        uint8(header_block.reward_chain_block.signage_point_index),
        None,
        None,
        None,
        None,
        header_block.reward_chain_block.challenge_chain_ip_vdf,
        header_block.reward_chain_block.infused_challenge_chain_ip_vdf,
        block_rec.total_iters,
    )
    return ssd


def handle_finished_slots(end_of_slot: EndOfSubSlotBundle, icc_end_of_slot_info: Optional[VDFInfo]) -> SubSlotData:
    return SubSlotData(
        None,
        None,
        None,
        None,
        None,
        None,
        None
        if end_of_slot.proofs.challenge_chain_slot_proof is None
        else end_of_slot.proofs.challenge_chain_slot_proof,
        None
        if end_of_slot.proofs.infused_challenge_chain_slot_proof is None
        else end_of_slot.proofs.infused_challenge_chain_slot_proof,
        end_of_slot.challenge_chain.challenge_chain_end_of_slot_vdf,
        icc_end_of_slot_info,
        None,
        None,
        None,
    )


def handle_end_of_slot(
    sub_slot: EndOfSubSlotBundle,
    eos_vdf_iters: uint64,
) -> SubSlotData:
    assert sub_slot.infused_challenge_chain
    assert sub_slot.proofs.infused_challenge_chain_slot_proof
    if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
        icc_info = sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
    else:
        icc_info = VDFInfo(
            sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge,
            eos_vdf_iters,
            sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output,
        )
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        cc_info = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf
    else:
        cc_info = VDFInfo(
            sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
            eos_vdf_iters,
            sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output,
        )

    assert sub_slot.proofs.infused_challenge_chain_slot_proof is not None
    return SubSlotData(
        None,
        None,
        None,
        None,
        None,
        None,
        sub_slot.proofs.challenge_chain_slot_proof,
        sub_slot.proofs.infused_challenge_chain_slot_proof,
        cc_info,
        icc_info,
        None,
        None,
        None,
    )


# wp validation methods
def _validate_sub_epoch_summaries(
    constants: ConsensusConstants,
    weight_proof: WeightProof,
) -> Tuple[Optional[List[SubEpochSummary]], Optional[List[uint128]]]:
    last_ses_hash, last_ses_sub_height = _get_last_ses_hash(constants, weight_proof.recent_chain_data)
    if last_ses_hash is None:
        log.warning("could not find last ses block")
        return None, None

    summaries, total, sub_epoch_weight_list = _map_sub_epoch_summaries(
        constants.SUB_EPOCH_BLOCKS,
        constants.GENESIS_CHALLENGE,
        weight_proof.sub_epochs,
        constants.DIFFICULTY_STARTING,
    )

    log.info(f"validating {len(summaries)} sub epochs")

    # validate weight
    if not _validate_summaries_weight(constants, total, summaries, weight_proof):
        log.error("failed validating weight")
        return None, None

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
            delta = 0
            if idx > 0:
                delta = sub_epoch_data[idx].num_blocks_overflow
            log.debug(f"sub epoch {idx} start weight is {total_weight+curr_difficulty} ")
            sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
            total_weight = uint128(
                total_weight
                + curr_difficulty * (sub_blocks_for_se + sub_epoch_data[idx + 1].num_blocks_overflow - delta)
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


def _validate_summaries_weight(
    constants: ConsensusConstants,
    sub_epoch_data_weight: uint128,
    summaries: List[SubEpochSummary],
    weight_proof: WeightProof,
) -> bool:
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
    constants: ConsensusConstants,
    rng: random.Random,
    weight_proof_bytes: bytes,
    summaries_bytes: List[bytes],
    height: uint32,
    validate_from: int = 0,
) -> Optional[List[Tuple[VDFProof, ClassgroupElement, VDFInfo]]]:
    summaries = summaries_from_bytes(summaries_bytes)
    sub_epoch_segments: SubEpochSegments = SubEpochSegments.from_bytes(weight_proof_bytes)
    rc_sub_slot_hash = constants.GENESIS_CHALLENGE
    total_blocks, total_ip_iters = 0, 0
    total_slot_iters, total_slots = 0, 0
    total_ip_iters = 0
    prev_ses: Optional[SubEpochSummary] = None
    segments_by_sub_epoch = map_segments_by_sub_epoch(sub_epoch_segments.challenge_segments)
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    vdfs_to_validate = []
    for sub_epoch_n, segments in segments_by_sub_epoch.items():
        prev_ssi = curr_ssi
        curr_difficulty, curr_ssi = _get_curr_diff_ssi(constants, sub_epoch_n, summaries)
        log.debug(f"validate sub epoch {sub_epoch_n}")
        # recreate RewardChainSubSlot for next ses rc_hash
        sampled_seg_index = rng.choice(range(len(segments)))
        if sub_epoch_n > 0:
            rc_sub_slot = __get_rc_sub_slot(constants, segments[0], summaries, curr_ssi)
            prev_ses = summaries[sub_epoch_n - 1]
            rc_sub_slot_hash = rc_sub_slot.get_hash()
        if not summaries[sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
            log.error(f"failed reward_chain_hash validation sub_epoch {sub_epoch_n}")
            return None

        # skip validation up to fork height
        if sub_epoch_n < validate_from:
            continue

        for idx, segment in enumerate(segments):
            valid_segment, ip_iters, slot_iters, slots, vdf_list = _validate_segment(
                constants,
                segment,
                curr_ssi,
                prev_ssi,
                curr_difficulty,
                prev_ses,
                idx == 0,
                sampled_seg_index == idx,
                height,
            )
            vdfs_to_validate.extend(vdf_list)
            if not valid_segment:
                log.error(f"failed to validate sub_epoch {segment.sub_epoch_n} segment {idx} slots")
                return None
            prev_ses = None
            total_blocks += 1
            total_slot_iters += slot_iters
            total_slots += slots
            total_ip_iters += ip_iters
    return vdfs_to_validate


def _validate_segment(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegment,
    curr_ssi: uint64,
    prev_ssi: uint64,
    curr_difficulty: uint64,
    ses: Optional[SubEpochSummary],
    first_segment_in_se: bool,
    sampled: bool,
    height: uint32,
) -> Tuple[bool, int, int, int, List[Tuple[VDFProof, ClassgroupElement, VDFInfo]]]:
    ip_iters, slot_iters, slots = 0, 0, 0
    after_challenge = False
    to_validate = []
    for idx, sub_slot_data in enumerate(segment.sub_slots):
        if sampled and sub_slot_data.is_challenge():
            after_challenge = True
            required_iters = __validate_pospace(
                constants, segment, idx, curr_difficulty, ses, first_segment_in_se, height
            )
            if required_iters is None:
                return False, uint64(0), uint64(0), uint64(0), []
            assert sub_slot_data.signage_point_index is not None
            ip_iters = ip_iters + calculate_ip_iters(
                constants, curr_ssi, sub_slot_data.signage_point_index, required_iters
            )
            vdf_list = _get_challenge_block_vdfs(constants, idx, segment.sub_slots, curr_ssi)
            to_validate.extend(vdf_list)
        elif sampled and after_challenge:
            validated, vdf_list = _validate_sub_slot_data(constants, idx, segment.sub_slots, curr_ssi)
            if not validated:
                log.error(f"failed to validate sub slot data {idx} vdfs")
                return False, uint64(0), uint64(0), uint64(0), []
            to_validate.extend(vdf_list)
        slot_iters = slot_iters + curr_ssi
        slots = slots + uint64(1)
    return True, ip_iters, slot_iters, slots, to_validate


def _get_challenge_block_vdfs(
    constants: ConsensusConstants,
    sub_slot_idx: int,
    sub_slots: List[SubSlotData],
    ssi: uint64,
) -> List[Tuple[VDFProof, ClassgroupElement, VDFInfo]]:
    to_validate = []
    sub_slot_data = sub_slots[sub_slot_idx]
    if sub_slot_data.cc_signage_point is not None and sub_slot_data.cc_sp_vdf_info:
        assert sub_slot_data.signage_point_index
        sp_input = ClassgroupElement.get_default_element()
        if not sub_slot_data.cc_signage_point.normalized_to_identity and sub_slot_idx >= 1:
            is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
            prev_ssd = sub_slots[sub_slot_idx - 1]
            sp_input = sub_slot_data_vdf_input(
                constants, sub_slot_data, sub_slot_idx, sub_slots, is_overflow, prev_ssd.is_end_of_slot(), ssi
            )
        to_validate.append((sub_slot_data.cc_signage_point, sp_input, sub_slot_data.cc_sp_vdf_info))

    assert sub_slot_data.cc_infusion_point
    assert sub_slot_data.cc_ip_vdf_info
    ip_input = ClassgroupElement.get_default_element()
    cc_ip_vdf_info = sub_slot_data.cc_ip_vdf_info
    if not sub_slot_data.cc_infusion_point.normalized_to_identity and sub_slot_idx >= 1:
        prev_ssd = sub_slots[sub_slot_idx - 1]
        if prev_ssd.cc_slot_end is None:
            assert prev_ssd.cc_ip_vdf_info
            assert prev_ssd.total_iters
            assert sub_slot_data.total_iters
            ip_input = prev_ssd.cc_ip_vdf_info.output
            ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
            cc_ip_vdf_info = VDFInfo(
                sub_slot_data.cc_ip_vdf_info.challenge, ip_vdf_iters, sub_slot_data.cc_ip_vdf_info.output
            )
    to_validate.append((sub_slot_data.cc_infusion_point, ip_input, cc_ip_vdf_info))

    return to_validate


def _validate_sub_slot_data(
    constants: ConsensusConstants,
    sub_slot_idx: int,
    sub_slots: List[SubSlotData],
    ssi: uint64,
) -> Tuple[bool, List[Tuple[VDFProof, ClassgroupElement, VDFInfo]]]:
    sub_slot_data = sub_slots[sub_slot_idx]
    assert sub_slot_idx > 0
    prev_ssd = sub_slots[sub_slot_idx - 1]
    to_validate = []
    if sub_slot_data.is_end_of_slot():
        if sub_slot_data.icc_slot_end is not None:
            input = ClassgroupElement.get_default_element()
            if not sub_slot_data.icc_slot_end.normalized_to_identity and prev_ssd.icc_ip_vdf_info is not None:
                assert prev_ssd.icc_ip_vdf_info
                input = prev_ssd.icc_ip_vdf_info.output
            assert sub_slot_data.icc_slot_end_info
            to_validate.append((sub_slot_data.icc_slot_end, input, sub_slot_data.icc_slot_end_info))
        assert sub_slot_data.cc_slot_end_info
        assert sub_slot_data.cc_slot_end
        input = ClassgroupElement.get_default_element()
        if (not prev_ssd.is_end_of_slot()) and (not sub_slot_data.cc_slot_end.normalized_to_identity):
            assert prev_ssd.cc_ip_vdf_info
            input = prev_ssd.cc_ip_vdf_info.output
        if not validate_vdf(sub_slot_data.cc_slot_end, constants, input, sub_slot_data.cc_slot_end_info):
            log.error(f"failed cc slot end validation  {sub_slot_data.cc_slot_end_info}")
            return False, []
    else:
        # find end of slot
        idx = sub_slot_idx
        while idx < len(sub_slots) - 1:
            curr_slot = sub_slots[idx]
            if curr_slot.is_end_of_slot():
                # dont validate intermediate vdfs if slot is blue boxed
                assert curr_slot.cc_slot_end
                if curr_slot.cc_slot_end.normalized_to_identity is True:
                    log.debug(f"skip intermediate vdfs slot {sub_slot_idx}")
                    return True, to_validate
                else:
                    break
            idx += 1
        if sub_slot_data.icc_infusion_point is not None and sub_slot_data.icc_ip_vdf_info is not None:
            input = ClassgroupElement.get_default_element()
            if not prev_ssd.is_challenge() and prev_ssd.icc_ip_vdf_info is not None:
                input = prev_ssd.icc_ip_vdf_info.output
            to_validate.append((sub_slot_data.icc_infusion_point, input, sub_slot_data.icc_ip_vdf_info))
        assert sub_slot_data.signage_point_index is not None
        if sub_slot_data.cc_signage_point:
            assert sub_slot_data.cc_sp_vdf_info
            input = ClassgroupElement.get_default_element()
            if not sub_slot_data.cc_signage_point.normalized_to_identity:
                is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
                input = sub_slot_data_vdf_input(
                    constants, sub_slot_data, sub_slot_idx, sub_slots, is_overflow, prev_ssd.is_end_of_slot(), ssi
                )
            to_validate.append((sub_slot_data.cc_signage_point, input, sub_slot_data.cc_sp_vdf_info))

        input = ClassgroupElement.get_default_element()
        assert sub_slot_data.cc_ip_vdf_info
        assert sub_slot_data.cc_infusion_point
        cc_ip_vdf_info = sub_slot_data.cc_ip_vdf_info
        if not sub_slot_data.cc_infusion_point.normalized_to_identity and prev_ssd.cc_slot_end is None:
            assert prev_ssd.cc_ip_vdf_info
            input = prev_ssd.cc_ip_vdf_info.output
            assert sub_slot_data.total_iters
            assert prev_ssd.total_iters
            ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
            cc_ip_vdf_info = VDFInfo(
                sub_slot_data.cc_ip_vdf_info.challenge, ip_vdf_iters, sub_slot_data.cc_ip_vdf_info.output
            )
        to_validate.append((sub_slot_data.cc_infusion_point, input, cc_ip_vdf_info))

    return True, to_validate


def sub_slot_data_vdf_input(
    constants: ConsensusConstants,
    sub_slot_data: SubSlotData,
    sub_slot_idx: int,
    sub_slots: List[SubSlotData],
    is_overflow: bool,
    new_sub_slot: bool,
    ssi: uint64,
) -> ClassgroupElement:
    cc_input = ClassgroupElement.get_default_element()
    sp_total_iters = get_sp_total_iters(constants, is_overflow, ssi, sub_slot_data)
    ssd: Optional[SubSlotData] = None
    if is_overflow and new_sub_slot:
        if sub_slot_idx >= 2:
            if sub_slots[sub_slot_idx - 2].cc_slot_end_info is None:
                for ssd_idx in reversed(range(0, sub_slot_idx - 1)):
                    ssd = sub_slots[ssd_idx]
                    if ssd.cc_slot_end_info is not None:
                        ssd = sub_slots[ssd_idx + 1]
                        break
                    assert ssd.total_iters is not None
                    if not (ssd.total_iters > sp_total_iters):
                        break
                if ssd and ssd.cc_ip_vdf_info is not None:
                    assert ssd.total_iters is not None
                    if ssd.total_iters < sp_total_iters:
                        cc_input = ssd.cc_ip_vdf_info.output
        return cc_input

    elif not is_overflow and not new_sub_slot:
        for ssd_idx in reversed(range(0, sub_slot_idx)):
            ssd = sub_slots[ssd_idx]
            if ssd.cc_slot_end_info is not None:
                ssd = sub_slots[ssd_idx + 1]
                break
            assert ssd.total_iters is not None
            if not (ssd.total_iters > sp_total_iters):
                break
        assert ssd is not None
        if ssd.cc_ip_vdf_info is not None:
            assert ssd.total_iters is not None
            if ssd.total_iters < sp_total_iters:
                cc_input = ssd.cc_ip_vdf_info.output
        return cc_input

    elif not new_sub_slot and is_overflow:
        slots_seen = 0
        for ssd_idx in reversed(range(0, sub_slot_idx)):
            ssd = sub_slots[ssd_idx]
            if ssd.cc_slot_end_info is not None:
                slots_seen += 1
                if slots_seen == 2:
                    return ClassgroupElement.get_default_element()
            if ssd.cc_slot_end_info is None:
                assert ssd.total_iters is not None
                if not (ssd.total_iters > sp_total_iters):
                    break
        assert ssd is not None
        if ssd.cc_ip_vdf_info is not None:
            assert ssd.total_iters is not None
            if ssd.total_iters < sp_total_iters:
                cc_input = ssd.cc_ip_vdf_info.output
    return cc_input


def validate_recent_blocks(
    constants: ConsensusConstants,
    recent_chain_bytes: bytes,
    summaries_bytes: List[bytes],
    shutdown_file_path: Optional[pathlib.Path] = None,
) -> Tuple[bool, List[bytes]]:
    recent_chain: RecentChainData = RecentChainData.from_bytes(recent_chain_bytes)
    summaries = summaries_from_bytes(summaries_bytes)
    sub_blocks = BlockCache({})
    first_ses_idx = _get_ses_idx(recent_chain.recent_chain_data)
    ses_idx = len(summaries) - len(first_ses_idx)
    ssi: uint64 = constants.SUB_SLOT_ITERS_STARTING
    diff: uint64 = constants.DIFFICULTY_STARTING
    last_blocks_to_validate = 100  # todo remove cap after benchmarks
    for summary in summaries[:ses_idx]:
        if summary.new_sub_slot_iters is not None:
            ssi = summary.new_sub_slot_iters
        if summary.new_difficulty is not None:
            diff = summary.new_difficulty

    ses_blocks, sub_slots, transaction_blocks = 0, 0, 0
    challenge, prev_challenge = recent_chain.recent_chain_data[0].reward_chain_block.pos_ss_cc_challenge_hash, None
    tip_height = recent_chain.recent_chain_data[-1].height
    prev_block_record: Optional[BlockRecord] = None
    deficit = uint8(0)
    adjusted = False
    for idx, block in enumerate(recent_chain.recent_chain_data):
        required_iters = uint64(0)
        overflow = False
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
            overflow = is_overflow_block(constants, uint8(block.reward_chain_block.signage_point_index))
            if not adjusted:
                assert prev_block_record is not None
                prev_block_record = dataclasses.replace(
                    prev_block_record, deficit=uint8(deficit % constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK)
                )
                sub_blocks.add_block_record(prev_block_record)
                adjusted = True
            deficit = get_deficit(constants, deficit, prev_block_record, overflow, len(block.finished_sub_slots))
            log.debug(f"wp, validate block {block.height}")
            if sub_slots > 2 and transaction_blocks > 11 and (tip_height - block.height < last_blocks_to_validate):
                caluclated_required_iters, error = validate_finished_header_block(
                    constants, sub_blocks, block, False, diff, ssi, ses_blocks > 2
                )
                if error is not None:
                    log.error(f"block {block.header_hash} failed validation {error}")
                    return False, []
                assert caluclated_required_iters is not None
                required_iters = caluclated_required_iters
            else:
                ret = _validate_pospace_recent_chain(constants, block, challenge, diff, overflow, prev_challenge)
                if ret is None:
                    return False, []
                required_iters = ret

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

        if shutdown_file_path is not None and not shutdown_file_path.is_file():
            log.info(f"cancelling block {block.header_hash} validation, shutdown requested")
            return False, []

    return True, [bytes(sub) for sub in sub_blocks._block_records.values()]


def _validate_pospace_recent_chain(
    constants: ConsensusConstants,
    block: HeaderBlock,
    challenge: bytes32,
    diff: uint64,
    overflow: bool,
    prev_challenge: bytes32,
) -> Optional[uint64]:
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        # Edge case of first sp (start of slot), where sp_iters == 0
        cc_sp_hash: bytes32 = challenge
    else:
        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
    assert cc_sp_hash is not None
    q_str = verify_and_get_quality_string(
        block.reward_chain_block.proof_of_space,
        constants,
        challenge if not overflow else prev_challenge,
        cc_sp_hash,
        height=block.height,
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
    segment: SubEpochChallengeSegment,
    idx: int,
    curr_diff: uint64,
    ses: Optional[SubEpochSummary],
    first_in_sub_epoch: bool,
    height: uint32,
) -> Optional[uint64]:
    if first_in_sub_epoch and segment.sub_epoch_n == 0 and idx == 0:
        cc_sub_slot_hash = constants.GENESIS_CHALLENGE
    else:
        cc_sub_slot_hash = __get_cc_sub_slot(segment.sub_slots, idx, ses).get_hash()

    sub_slot_data: SubSlotData = segment.sub_slots[idx]

    if sub_slot_data.signage_point_index and is_overflow_block(constants, sub_slot_data.signage_point_index):
        curr_slot = segment.sub_slots[idx - 1]
        assert curr_slot.cc_slot_end_info
        challenge = curr_slot.cc_slot_end_info.challenge
    else:
        challenge = cc_sub_slot_hash

    if sub_slot_data.cc_sp_vdf_info is None:
        cc_sp_hash = cc_sub_slot_hash
    else:
        cc_sp_hash = sub_slot_data.cc_sp_vdf_info.output.get_hash()

    # validate proof of space
    assert sub_slot_data.proof_of_space is not None
    q_str = verify_and_get_quality_string(
        sub_slot_data.proof_of_space,
        constants,
        challenge,
        cc_sp_hash,
        height=height,
    )
    if q_str is None:
        log.error("could not verify proof of space")
        return None
    return calculate_iterations_quality(
        constants.DIFFICULTY_CONSTANT_FACTOR,
        q_str,
        sub_slot_data.proof_of_space.size,
        curr_diff,
        cc_sp_hash,
    )


def __get_rc_sub_slot(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegment,
    summaries: List[SubEpochSummary],
    curr_ssi: uint64,
) -> RewardChainSubSlot:
    ses = summaries[uint32(segment.sub_epoch_n - 1)]
    # find first challenge in sub epoch
    first_idx = None
    first = None
    for idx, curr in enumerate(segment.sub_slots):
        if curr.cc_slot_end is None:
            first_idx = idx
            first = curr
            break

    assert first_idx
    idx = first_idx
    slots = segment.sub_slots

    # number of slots to look for
    slots_n = 1
    assert first
    assert first.signage_point_index is not None
    if is_overflow_block(constants, first.signage_point_index):
        if idx >= 2 and slots[idx - 2].cc_slot_end is None:
            slots_n = 2

    new_diff = None if ses is None else ses.new_difficulty
    new_ssi = None if ses is None else ses.new_sub_slot_iters
    ses_hash: Optional[bytes32] = None if ses is None else ses.get_hash()
    overflow = is_overflow_block(constants, first.signage_point_index)
    if overflow:
        if idx >= 2 and slots[idx - 2].cc_slot_end is not None and slots[idx - 1].cc_slot_end is not None:
            ses_hash = None
            new_ssi = None
            new_diff = None

    sub_slot = slots[idx]
    while True:
        if sub_slot.cc_slot_end:
            slots_n -= 1
            if slots_n == 0:
                break
        idx -= 1
        sub_slot = slots[idx]

    icc_sub_slot_hash: Optional[bytes32] = None
    assert sub_slot is not None
    assert sub_slot.cc_slot_end_info is not None

    assert segment.rc_slot_end_info is not None
    if idx != 0:
        # this is not the first slot, ses details should not be included
        ses_hash = None
        new_ssi = None
        new_diff = None
        cc_vdf_info = VDFInfo(sub_slot.cc_slot_end_info.challenge, curr_ssi, sub_slot.cc_slot_end_info.output)
        if sub_slot.icc_slot_end_info is not None:
            icc_slot_end_info = VDFInfo(
                sub_slot.icc_slot_end_info.challenge, curr_ssi, sub_slot.icc_slot_end_info.output
            )
            icc_sub_slot_hash = icc_slot_end_info.get_hash()
    else:
        cc_vdf_info = sub_slot.cc_slot_end_info
        if sub_slot.icc_slot_end_info is not None:
            icc_sub_slot_hash = sub_slot.icc_slot_end_info.get_hash()
    cc_sub_slot = ChallengeChainSubSlot(
        cc_vdf_info,
        icc_sub_slot_hash,
        ses_hash,
        new_ssi,
        new_diff,
    )

    rc_sub_slot = RewardChainSubSlot(
        segment.rc_slot_end_info,
        cc_sub_slot.get_hash(),
        icc_sub_slot_hash,
        constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK,
    )
    return rc_sub_slot


def __get_cc_sub_slot(sub_slots: List[SubSlotData], idx: int, ses: Optional[SubEpochSummary]) -> ChallengeChainSubSlot:
    sub_slot: Optional[SubSlotData] = None
    for i in reversed(range(0, idx)):
        sub_slot = sub_slots[i]
        if sub_slot.cc_slot_end_info is not None:
            break

    assert sub_slot is not None
    assert sub_slot.cc_slot_end_info is not None

    icc_vdf = sub_slot.icc_slot_end_info
    icc_vdf_hash: Optional[bytes32] = None
    if icc_vdf is not None:
        icc_vdf_hash = icc_vdf.get_hash()
    cc_sub_slot = ChallengeChainSubSlot(
        sub_slot.cc_slot_end_info,
        icc_vdf_hash,
        None if ses is None else ses.get_hash(),
        None if ses is None else ses.new_sub_slot_iters,
        None if ses is None else ses.new_difficulty,
    )

    return cc_sub_slot


def _get_curr_diff_ssi(
    constants: ConsensusConstants, idx: int, summaries: List[SubEpochSummary]
) -> Tuple[uint64, uint64]:
    curr_difficulty = constants.DIFFICULTY_STARTING
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    for ses in reversed(summaries[0:idx]):
        if ses.new_sub_slot_iters is not None:
            curr_ssi = ses.new_sub_slot_iters
            assert ses.new_difficulty is not None
            curr_difficulty = ses.new_difficulty
            break

    return curr_difficulty, curr_ssi


def vars_to_bytes(summaries: List[SubEpochSummary], weight_proof: WeightProof) -> Tuple[List[bytes], bytes, bytes]:
    wp_recent_chain_bytes = bytes(RecentChainData(weight_proof.recent_chain_data))
    wp_segment_bytes = bytes(SubEpochSegments(weight_proof.sub_epoch_segments))
    summary_bytes = []
    for summary in summaries:
        summary_bytes.append(bytes(summary))
    return summary_bytes, wp_segment_bytes, wp_recent_chain_bytes


def summaries_from_bytes(summaries_bytes: List[bytes]) -> List[SubEpochSummary]:
    summaries = []
    for summary in summaries_bytes:
        summaries.append(SubEpochSummary.from_bytes(summary))
    return summaries


def _get_last_ses_hash(
    constants: ConsensusConstants, recent_reward_chain: List[HeaderBlock]
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
                                uint32(curr.reward_chain_block.height),
                            )
                idx += 1
    return None, uint32(0)


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
    prev_block: Optional[BlockRecord],
    overflow: bool,
    num_finished_sub_slots: int,
) -> uint8:
    if prev_block is None:
        if curr_deficit >= 1 and not (overflow and curr_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK):
            curr_deficit = uint8(curr_deficit - 1)
        return curr_deficit

    return calculate_deficit(constants, uint32(prev_block.height + 1), prev_block, overflow, num_finished_sub_slots)


def get_sp_total_iters(
    constants: ConsensusConstants, is_overflow: bool, ssi: uint64, sub_slot_data: SubSlotData
) -> int:
    assert sub_slot_data.cc_ip_vdf_info is not None
    assert sub_slot_data.total_iters is not None
    assert sub_slot_data.signage_point_index is not None
    sp_iters: uint64 = calculate_sp_iters(constants, ssi, sub_slot_data.signage_point_index)
    ip_iters: uint64 = uint64(sub_slot_data.cc_ip_vdf_info.number_of_iterations)
    sp_sub_slot_total_iters = uint128(sub_slot_data.total_iters - ip_iters)
    if is_overflow:
        sp_sub_slot_total_iters = uint128(sp_sub_slot_total_iters - ssi)
    return sp_sub_slot_total_iters + sp_iters


def blue_boxed_end_of_slot(sub_slot: EndOfSubSlotBundle) -> bool:
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
            if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                return True
        else:
            return True
    return False


def validate_sub_epoch_sampling(
    rng: random.Random, sub_epoch_weight_list: List[uint128], weight_proof: WeightProof
) -> bool:
    tip = weight_proof.recent_chain_data[-1]
    weight_to_check = _get_weights_for_sampling(rng, tip.weight, weight_proof.recent_chain_data)
    sampled_sub_epochs: Dict[int, bool] = {}
    for idx in range(1, len(sub_epoch_weight_list)):
        if _sample_sub_epoch(sub_epoch_weight_list[idx - 1], sub_epoch_weight_list[idx], weight_to_check):
            sampled_sub_epochs[idx - 1] = True
            if len(sampled_sub_epochs) == WeightProofHandler.MAX_SAMPLES:
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


def map_segments_by_sub_epoch(
    sub_epoch_segments: List[SubEpochChallengeSegment],
) -> Dict[int, List[SubEpochChallengeSegment]]:
    segments: Dict[int, List[SubEpochChallengeSegment]] = {}
    curr_sub_epoch_n = -1
    for idx, segment in enumerate(sub_epoch_segments):
        if curr_sub_epoch_n < segment.sub_epoch_n:
            curr_sub_epoch_n = segment.sub_epoch_n
            segments[curr_sub_epoch_n] = []
        segments[curr_sub_epoch_n].append(segment)
    return segments


def _validate_vdf_batch(
    constants: ConsensusConstants,
    vdf_list: List[Tuple[bytes, bytes, bytes]],
    shutdown_file_path: Optional[pathlib.Path] = None,
) -> bool:
    for vdf_proof_bytes, class_group_bytes, info in vdf_list:
        vdf = VDFProof.from_bytes(vdf_proof_bytes)
        class_group = ClassgroupElement.create(class_group_bytes)
        vdf_info = VDFInfo.from_bytes(info)
        if not validate_vdf(vdf, constants, class_group, vdf_info):
            return False

        if shutdown_file_path is not None and not shutdown_file_path.is_file():
            log.info("cancelling VDF validation, shutdown requested")
            return False

    return True


async def validate_weight_proof_inner(
    constants: ConsensusConstants,
    executor: ProcessPoolExecutor,
    shutdown_file_name: str,
    num_processes: int,
    weight_proof: WeightProof,
    summaries: List[SubEpochSummary],
    sub_epoch_weight_list: List[uint128],
    skip_segment_validation: bool,
    validate_from: int,
) -> Tuple[bool, List[BlockRecord]]:
    assert len(weight_proof.sub_epochs) > 0
    if len(weight_proof.sub_epochs) == 0:
        return False, []

    peak_height = uint32(weight_proof.recent_chain_data[-1].reward_chain_block.height)
    log.info(f"validate weight proof peak height {peak_height}")
    seed = summaries[-2].get_hash()
    rng = random.Random(seed)
    if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
        log.error("failed weight proof sub epoch sample validation")
        return False, []

    loop = asyncio.get_running_loop()
    summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(summaries, weight_proof)
    recent_blocks_validation_task = loop.run_in_executor(
        executor,
        validate_recent_blocks,
        constants,
        wp_recent_chain_bytes,
        summary_bytes,
        pathlib.Path(shutdown_file_name),
    )

    if not skip_segment_validation:
        vdfs_to_validate = _validate_sub_epoch_segments(
            constants, rng, wp_segment_bytes, summary_bytes, peak_height, validate_from
        )
        await asyncio.sleep(0)  # break up otherwise multi-second sync code

        if vdfs_to_validate is None:
            return False, []

        vdf_tasks = []
        for batch in to_batches(vdfs_to_validate, num_processes):
            byte_chunks = []
            for vdf_proof, classgroup, vdf_info in batch.entries:
                byte_chunks.append((bytes(vdf_proof), bytes(classgroup), bytes(vdf_info)))
            vdf_task = asyncio.get_running_loop().run_in_executor(
                executor,
                _validate_vdf_batch,
                constants,
                byte_chunks,
                pathlib.Path(shutdown_file_name),
            )
            vdf_tasks.append(vdf_task)
            # give other stuff a turn
            await asyncio.sleep(0)

        for vdf_task in asyncio.as_completed(fs=vdf_tasks):
            validated = await vdf_task
            if not validated:
                return False, []

    valid_recent_blocks, records_bytes = await recent_blocks_validation_task

    if not valid_recent_blocks or records_bytes is None:
        log.error("failed validating weight proof recent blocks")
        # Verify the data
        return False, []

    records = [BlockRecord.from_bytes(b) for b in records_bytes]
    return True, records
