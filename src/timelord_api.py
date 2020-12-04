from typing import Callable
import logging
from src.protocols import timelord_protocol
from src.timelord import Timelord, iters_from_sub_block, Chain, IterationType
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
    async def new_peak(self, new_peak: timelord_protocol.NewPeak):
        async with self.timelord.lock:
            if self.timelord.last_state.peak == new_peak:
                log.info("Skipping peak, already have.")
                return
            elif new_peak.reward_chain_sub_block.weight > self.timelord.last_state.get_weight():
                log.warning("Not skipping peak, don't have. Maybe we are not the fastest timelord")
                log.warning(f"Our peak: {self.timelord.last_state.peak} new peak{new_peak}")
                self.timelord.new_peak = new_peak
            else:
                log.info("Peak at smaller weight, skipping")

    @api_request
    async def new_unfinished_sub_block(self, new_unfinished_subblock: timelord_protocol.NewUnfinishedSubBlock):
        async with self.timelord.lock:
            sp_iters, ip_iters = iters_from_sub_block(
                self.timelord.constants,
                new_unfinished_subblock.reward_chain_sub_block,
                self.timelord.last_state.get_sub_slot_iters(),
                self.timelord.last_state.get_difficulty(),
            )
            last_ip_iters = self.timelord.last_state.get_last_ip()
            if sp_iters > ip_iters:
                self.timelord.overflow_blocks.append(new_unfinished_subblock)
            elif ip_iters > last_ip_iters:
                self.timelord.unfinished_blocks.append(new_unfinished_subblock)
                for chain in Chain:
                    self.timelord.iters_to_submit[chain].append(uint64(ip_iters - last_ip_iters))
                self.timelord.iteration_to_proof_type[ip_iters - last_ip_iters] = IterationType.INFUSION_POINT
