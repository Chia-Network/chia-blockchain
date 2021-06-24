from chia.full_node.fee_estimate import FeeEstimate
from chia.full_node.mempool_manager import MempoolManager


class FeeEstimator:
    def __init__(self, mempool_mgr: MempoolManager, log):
        self.log = log
        self.mempool_manager = mempool_mgr

    def get_estimates(self) -> FeeEstimate:
        if self.mempool_manager.peak is None or self.mempool_manager.fee_tracker.latest_seen_height == 0:
            return FeeEstimate("no enough data", -1, -1, -1)

        tracking_length = (
            self.mempool_manager.fee_tracker.latest_seen_height - self.mempool_manager.fee_tracker.first_recorded_height
        )
        if tracking_length < 20:
            return FeeEstimate("no enough data", -1, -1, -1)

        if self.mempool_manager.mempool.total_mempool_cost < self.mempool_manager.constants.MAX_BLOCK_COST_CLVM * 0.8:
            return FeeEstimate(None, 0, 0, 0)

        short, med, long = self.mempool_manager.fee_tracker.estimate_fee()
        short_fee = short[2]
        med_fee = med[2]
        long_fee = long[2]
        # convert from mojo / 1000 clvm_cost to mojo / 1 clvm_cost
        if short_fee != -1:
            short_fee = short_fee / 1000
        if med_fee != -1:
            med_fee = med_fee / 1000
        if long_fee != -1:
            long_fee = long_fee / 1000
        return FeeEstimate(None, short_fee, med_fee, long_fee)
