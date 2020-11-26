from typing import Callable

from src.protocols import timelord_protocol
from src.timelord_new import Timelord
from src.timelord_new import IterationType, iters_from_sub_block
from src.util.api_decorators import api_request
from src.util.ints import uint64


class TimelordAPI:
    timelord: Timelord

    def __init__(self, timelord):
        self.timelord = timelord

    def _set_state_changed_callback(self, callback: Callable):
        pass

    @property
    def lock(self):
        return self.timelord.lock

    @api_request
    async def new_peak(self, new_peak: timelord_protocol.NewPeak):
        async with self.lock:
            if (
                    self.timelord.last_state is None
                    or self.timelord.last_state.get_weight() < new_peak.weight
            ):
                self.new_peak = new_peak

    @api_request
    async def new_unfinished_subblock(self, new_unfinished_subblock: timelord_protocol.NewUnfinishedSubBlock):
        async with self.lock:
            if not self.timelord._accept_unfinished_block(new_unfinished_subblock):
                return
            sp_iters, ip_iters = iters_from_sub_block(
                new_unfinished_subblock.reward_chain_sub_block,
                self.timelord.last_state.get_ips(),
                self.timelord.last_state.get_difficulty(),
            )
            last_ip_iters = self.timelord.last_state.get_last_ip()
            if sp_iters < ip_iters:
                self.timelord.overflow_blocks.append(new_unfinished_subblock)
            elif ip_iters > last_ip_iters:
                self.timelord.unfinished_blocks.append(new_unfinished_subblock)
                for chain in Chain:
                    self.timelord.iters_to_submit[chain].append(uint64(ip_iters - last_ip_iters))
                self.timelord.iteration_to_proof_type[ip_iters - self.timelord.last_ip_iters] = IterationType.INFUSION_POINT
