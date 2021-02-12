from typing import Callable, Optional
import logging
from src.protocols import timelord_protocol
from src.timelord.timelord import Timelord, iters_from_block, Chain, IterationType
from src.util.api_decorators import api_request
from src.util.ints import uint64


log = logging.getLogger(__name__)


class TimelordAPI:
    timelord: Timelord

    def __init__(self, timelord):
        self.timelord = timelord

    def _set_state_changed_callback(self, callback: Callable):
        pass

    @api_request
    async def new_peak_timelord(self, new_peak: timelord_protocol.NewPeakTimelord):
        async with self.timelord.lock:
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
                return
            else:
                log.warning("block that we don't have, changing to it.")
                self.timelord.new_peak = new_peak
                self.timelord.new_subslot_end = None

    @api_request
    async def new_unfinished_block(self, new_unfinished_block: timelord_protocol.NewUnfinishedBlock):
        async with self.timelord.lock:
            try:
                sp_iters, ip_iters = iters_from_block(
                    self.timelord.constants,
                    new_unfinished_block.reward_chain_block,
                    self.timelord.last_state.get_sub_slot_iters(),
                    self.timelord.last_state.get_difficulty(),
                )
            except Exception:
                return
            last_ip_iters = self.timelord.last_state.get_last_ip()
            if sp_iters > ip_iters:
                self.timelord.overflow_blocks.append(new_unfinished_block)
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
