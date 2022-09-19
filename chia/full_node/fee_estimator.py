import logging

from chia.full_node.fee_estimate import FeeEstimates, FeeEstimate
from chia.full_node.fee_tracker import EstimateResult, BucketResult, get_estimate_time_intervals, FeeTracker
from chia.policy.fee_estimation import FeeMempoolInfo
from chia.util.ints import uint64, uint32


# #https://github.com/bitcoin/bitcoin/blob/master/src/policy/fees.cpp
class SmartFeeEstimator:
    def __init__(self, fee_tracker: FeeTracker, max_block_cost_clvm: uint64):
        self.log = logging.getLogger(__name__)
        self.fee_tracker = fee_tracker
        self.max_block_cost_clvm = max_block_cost_clvm

    def parse(self, fee_result: EstimateResult) -> float:  # xxx parse should be replaced.
        # self.log.debug(f"parse(fee_result: {fee_result})")
        fail_bucket: BucketResult = fee_result.fail_bucket
        median = fee_result.median

        if median != -1:
            return median

        if fail_bucket["start"] == 0:
            return -1.0

        # If median is -1, tracker wasn't able to find a passing bucket.
        # Suggest one bucket higher than the lowest failing bucket.

        # XXX Fix this comment
        # get_bucket_index return left (-1) bucket
        # start value is already -1
        # Thus +3 because we want +1 from the lowest bucket it failed at
        max_val = len(self.fee_tracker.buckets) - 1
        start_index = min(self.fee_tracker.get_bucket_index(fail_bucket["start"]) + 3, max_val)

        fee_val: float = self.fee_tracker.buckets[start_index]
        return fee_val

    def get_estimate_for_block(self, block: uint32, ignore_mempool: bool = False) -> FeeEstimate:
        estimate_result = self.fee_tracker.estimate_fee_for_block(block)
        return self.estimate_result_to_fee_estimate(estimate_result)

    def get_estimate(self, time_delta_seconds: int, ignore_mempool: bool = False) -> FeeEstimate:
        estimate_result = self.fee_tracker.estimate_fee(time_delta_seconds)
        return self.estimate_result_to_fee_estimate(estimate_result)

    def get_estimates(self, mempool_info: FeeMempoolInfo, ignore_mempool: bool = False) -> FeeEstimates:
        self.log.error(self.fee_tracker.buckets)
        short_time_seconds, med_time_seconds, long_time_seconds = get_estimate_time_intervals()

        if ignore_mempool is False and (self.fee_tracker.latest_seen_height == 0):
            # return FeeEstimate("No enough data", "-1", "-1", "-1") #xxx
            return FeeEstimates(error="Not enough data", estimates=[])
            # return FeeEstimates(error="Not enough data", estimates=[short_none, med_none, long_none])

        tracking_length = self.fee_tracker.latest_seen_height - self.fee_tracker.first_recorded_height
        if tracking_length < 20:
            # return FeeEstimate("No enough data", "-1", "-1", "-1")
            return FeeEstimates(error="Not enough data", estimates=[])
            # return FeeEstimates(error="Not enough data", estimates=[short_none, med_none, long_none])

        if ignore_mempool is False and mempool_info.current_mempool_cost < int(mempool_info.MAX_BLOCK_COST_CLVM * 0.8):
            return FeeEstimates(
                error=None,
                estimates=[
                    FeeEstimate(
                        None, uint64(short_time_seconds), uint64(0)
                    ),  # xxx time_target is an offset, not  a unix timestamp
                    FeeEstimate(None, uint64(med_time_seconds), uint64(0)),
                    FeeEstimate(None, uint64(long_time_seconds), uint64(0)),
                ],
            )

        short_result, med_result, long_result = self.fee_tracker.estimate_fees()

        short = self.estimate_result_to_fee_estimate(short_result)
        med = self.estimate_result_to_fee_estimate(med_result)
        long = self.estimate_result_to_fee_estimate(long_result)

        return FeeEstimates(
            error=None,
            # xxx fix: time_target is an offset, not a unix timestamp
            estimates=[short, med, long],
        )

    def estimate_result_to_fee_estimate(self, r: EstimateResult) -> FeeEstimate:
        fee: float = self.parse(r)
        if fee == -1 or r.median == -1:
            return FeeEstimate("Not enough data", r.requested_time, uint64(0))
        else:
            # convert from mojo / 1000 clvm_cost to mojo / 1 clvm_cost
            return FeeEstimate(None, r.requested_time, uint64(fee / 1000))

    # TODO: remove self.parse
    # TODO: fit Bitcoin -1 error to our errors better
