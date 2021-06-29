from chia.full_node.fee_estimate import FeeEstimate
from chia.full_node.mempool_manager import MempoolManager


class SmartFeeEstimator:
    def __init__(self, mempool_mgr: MempoolManager, log):
        self.log = log
        self.mempool_manager = mempool_mgr

    def parse(self, fee_result):
        pass_bucket, fail_bucket, median = fee_result

        if median != -1:
            return median

        self.log.debug(f"fee_result: {fee_result}")

        # If median is -1 tracker wasn't able to find a passing bucket,
        # Suggest one bucket higher than lowest failing bucket
        if "start" in fail_bucket:
            # get_bucket_index return left (-1) bucket
            # start value is already -1
            # Thus +3 because we want +1 from the lowest bucket it failed at
            max_val = len(self.mempool_manager.fee_tracker.buckets) - 1
            start_index = min(self.mempool_manager.fee_tracker.get_bucket_index(fail_bucket["start"]) + 3, max_val)

            fee_val = self.mempool_manager.fee_tracker.buckets[start_index]
            return fee_val

        return -1

    def get_estimates(self, ignore_mempool=False) -> FeeEstimate:
        if ignore_mempool is False and (
            self.mempool_manager.peak is None or self.mempool_manager.fee_tracker.latest_seen_height == 0
        ):
            return FeeEstimate("no enough data", "-1", "-1", "-1")

        tracking_length = (
            self.mempool_manager.fee_tracker.latest_seen_height - self.mempool_manager.fee_tracker.first_recorded_height
        )
        if tracking_length < 20:
            return FeeEstimate("no enough data", "-1", "-1", "-1")

        if (
            ignore_mempool is False
            and self.mempool_manager.mempool.total_mempool_cost
            < self.mempool_manager.constants.MAX_BLOCK_COST_CLVM * 0.8
        ):
            return FeeEstimate(None, "0", "0", "0")

        short, med, long = self.mempool_manager.fee_tracker.estimate_fee()
        short_fee = self.parse(short)
        med_fee = self.parse(med)
        long_fee = self.parse(long)

        # convert from mojo / 1000 clvm_cost to mojo / 1 clvm_cost
        if short_fee != -1:
            short_fee = short_fee / 1000
        if med_fee != -1:
            med_fee = med_fee / 1000
        if long_fee != -1:
            long_fee = long_fee / 1000
        return FeeEstimate(None, f"{short_fee}", f"{med_fee}", f"{long_fee}")
