import logging
from typing import Callable, Optional

from chia.protocols import timelord_protocol
from chia.timelord.timelord import Chain, IterationType, Timelord, iters_from_block
from chia.util.api_decorators import api_request
from chia.util.ints import uint64

log = logging.getLogger(__name__)


class TimelordAPI:
    timelord: Timelord

    def __init__(self, timelord) -> None:
        self.timelord = timelord

    def _set_state_changed_callback(self, callback: Callable):
        pass

    @api_request
    async def new_peak_timelord(self, new_peak: timelord_protocol.NewPeakTimelord):
        if self.timelord.last_state is None:
            return None
        async with self.timelord.lock:
            if self.timelord.sanitizer_mode:
                return None
            if new_peak.reward_chain_block.weight > self.timelord.last_state.get_weight():
                log.info("Not skipping peak, don't have. Maybe we are not the fastest timelord")
                log.info(
                    f"New peak: height: {new_peak.reward_chain_block.height} weight: "
                    f"{new_peak.reward_chain_block.weight} "
                )
                self.timelord.new_peak = new_peak
            elif (
                self.timelord.last_state.peak is not None
                and self.timelord.last_state.peak.reward_chain_block == new_peak.reward_chain_block
            ):
                log.info("Skipping peak, already have.")
                return None
            else:
                log.warning("block that we don't have, changing to it.")
                self.timelord.new_peak = new_peak
                self.timelord.new_subslot_end = None

    @api_request
    async def new_unfinished_block_timelord(self, new_unfinished_block: timelord_protocol.NewUnfinishedBlockTimelord):
        if self.timelord.last_state is None:
            return None
        async with self.timelord.lock:
            if self.timelord.sanitizer_mode:
                return None
            try:
                sp_iters, ip_iters = iters_from_block(
                    self.timelord.constants,
                    new_unfinished_block.reward_chain_block,
                    self.timelord.last_state.get_sub_slot_iters(),
                    self.timelord.last_state.get_difficulty(),
                )
            except Exception:
                return None
            last_ip_iters = self.timelord.last_state.get_last_ip()
            if sp_iters > ip_iters:
                self.timelord.overflow_blocks.append(new_unfinished_block)
                log.debug(f"Overflow unfinished block, total {self.timelord.total_unfinished}")
            elif ip_iters > last_ip_iters:
                new_block_iters: Optional[uint64] = self.timelord._can_infuse_unfinished_block(new_unfinished_block)
                if new_block_iters:
                    self.timelord.unfinished_blocks.append(new_unfinished_block)
                    for chain in [Chain.REWARD_CHAIN, Chain.CHALLENGE_CHAIN]:
                        self.timelord.iters_to_submit[chain].append(new_block_iters)
                    if self.timelord.last_state.get_deficit() < self.timelord.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                        self.timelord.iters_to_submit[Chain.INFUSED_CHALLENGE_CHAIN].append(new_block_iters)
                    self.timelord.iteration_to_proof_type[new_block_iters] = IterationType.INFUSION_POINT
                    self.timelord.total_unfinished += 1
                    log.debug(f"Non-overflow unfinished block, total {self.timelord.total_unfinished}")

    @api_request
    async def request_compact_proof_of_time(self, vdf_info: timelord_protocol.RequestCompactProofOfTime):
        async with self.timelord.lock:
            if not self.timelord.sanitizer_mode:
                return None
            if vdf_info not in self.timelord.pending_bluebox_info:
                self.timelord.pending_bluebox_info.append(vdf_info)
