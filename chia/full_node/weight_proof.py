from __future__ import annotations

import asyncio
import logging
import random
from concurrent.futures.process import ProcessPoolExecutor
from multiprocessing.context import BaseContext
from typing import Optional

from chia_rs import (
    BlockRecord,
    ConsensusConstants,
    HeaderBlock,
    SubEpochChallengeSegment,
    SubEpochData,
    SubEpochSummary,
    SubSlotData,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.full_node.weight_proof_utils import (
    LAMBDA_L,
    MAX_SAMPLES,
    C,
    _challenge_block_vdfs,
    _create_shutdown_file,
    _create_sub_epoch_data,
    _get_weights_for_sampling,
    _map_sub_epoch_summaries,
    _sample_sub_epoch,
    _validate_sub_epoch_segments,
    _validate_sub_epoch_summaries,
    _validate_summaries_weight,
    blue_boxed_end_of_slot,
    handle_end_of_slot,
    handle_finished_slots,
    validate_recent_blocks,
    validate_sub_epoch_sampling,
    validate_weight_proof_inner,
    vars_to_bytes,
)
from chia.types.blockchain_format.vdf import VDFInfo
from chia.types.weight_proof import (
    WeightProof,
)
from chia.util.block_cache import BlockCache
from chia.util.setproctitle import getproctitle, setproctitle
from chia.util.task_referencer import create_referenced_task

log = logging.getLogger(__name__)

__all__ = [
    "WeightProofHandler",
    "_map_sub_epoch_summaries",
    "_validate_summaries_weight",
]


class WeightProofHandler:
    LAMBDA_L = LAMBDA_L
    C = C
    MAX_SAMPLES = MAX_SAMPLES

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

    def get_sub_epoch_data(self, tip_height: uint32, summary_heights: list[uint32]) -> list[SubEpochData]:
        sub_epoch_data: list[SubEpochData] = []
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
        sub_epoch_segments: list[SubEpochChallengeSegment] = []
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

    def get_seed_for_proof(self, summary_heights: list[uint32], tip_height: uint32) -> bytes32:
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

    async def _get_recent_chain(self, tip_height: uint32) -> Optional[list[HeaderBlock]]:
        recent_chain: list[HeaderBlock] = []
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
    ) -> Optional[list[SubEpochChallengeSegment]]:
        segments: list[SubEpochChallengeSegment] = []
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
        header_blocks: dict[bytes32, HeaderBlock],
        blocks: dict[bytes32, BlockRecord],
        first_segment_in_sub_epoch: bool,
    ) -> tuple[Optional[SubEpochChallengeSegment], uint32]:
        assert self.blockchain is not None
        sub_slots: list[SubSlotData] = []
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
        header_blocks: dict[bytes32, HeaderBlock],
        blocks: dict[bytes32, BlockRecord],
        first_in_sub_epoch: bool,
    ) -> tuple[Optional[list[SubSlotData]], Optional[VDFInfo]]:
        # combine cc vdfs of all reward blocks from the start of the sub slot to end
        header_block_sub_rec = blocks[header_block.header_hash]
        # find slot start
        curr_sub_rec = header_block_sub_rec
        first_rc_end_of_slot_vdf = None
        if first_in_sub_epoch and curr_sub_rec.height > 0:
            while not curr_sub_rec.sub_epoch_summary_included:
                curr_sub_rec = blocks[curr_sub_rec.prev_hash]
            first_rc_end_of_slot_vdf = self.first_rc_end_of_slot_vdf(header_block, blocks, header_blocks)
        elif header_block_sub_rec.overflow and header_block_sub_rec.first_in_sub_slot:
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
        sub_slots_data: list[SubSlotData] = []
        tmp_sub_slots_data: list[SubSlotData] = []
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
                curr.reward_chain_block.signage_point_index,
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
        blocks: dict[bytes32, BlockRecord],
        header_blocks: dict[bytes32, HeaderBlock],
    ) -> Optional[VDFInfo]:
        curr = blocks[header_block.header_hash]
        while curr.height > 0 and not curr.sub_epoch_summary_included:
            curr = blocks[curr.prev_hash]
        return header_blocks[curr.header_hash].finished_sub_slots[-1].reward_chain.end_of_slot_vdf

    async def __slot_end_vdf(
        self, start_height: uint32, header_blocks: dict[bytes32, HeaderBlock], blocks: dict[bytes32, BlockRecord]
    ) -> tuple[Optional[list[SubSlotData]], uint32]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        log.debug(f"slot end vdf start height {start_height}")
        header_hash = self.blockchain.height_to_hash(start_height)
        assert header_hash is not None
        curr = header_blocks[header_hash]
        curr_header_hash = curr.header_hash
        sub_slots_data: list[SubSlotData] = []
        tmp_sub_slots_data: list[SubSlotData] = []
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

    def handle_block_vdfs(self, curr: HeaderBlock, blocks: dict[bytes32, BlockRecord]) -> SubSlotData:
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
            curr.reward_chain_block.signage_point_index,
            None,
            None,
            None,
            None,
            curr.reward_chain_block.challenge_chain_ip_vdf,
            icc_ip_info,
            curr.total_iters,
        )

    def validate_weight_proof_single_proc(self, weight_proof: WeightProof) -> tuple[bool, uint32]:
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

    async def validate_weight_proof(self, weight_proof: WeightProof) -> tuple[bool, uint32, list[SubEpochSummary]]:
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
                task = create_referenced_task(
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

    def get_fork_point(self, received_summaries: list[SubEpochSummary]) -> tuple[uint32, int]:
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
            # Two summaries can have different blocks and still be identical
            # This gets resolved after one full sub epoch
            return uint32(0), 0

        return ses_heights[fork_point_index - 2], fork_point_index
