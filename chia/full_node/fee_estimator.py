from __future__ import annotations

import logging
from dataclasses import dataclass, field

from chia.full_node.fee_estimate import FeeEstimate, FeeEstimateGroup, FeeEstimateV2, fee_estimate_v2_to_v1
from chia.full_node.fee_estimation import FeeMempoolInfo
from chia.full_node.fee_tracker import (
    BucketResult,
    EstimateResult,
    FeeTracker,
    get_bucket_index,
    get_estimate_time_intervals,
)
from chia.types.fee_rate import FeeRate, FeeRateV2
from chia.util.ints import uint32, uint64


# https://github.com/bitcoin/bitcoin/blob/5b6f0f31fa6ce85db3fb7f9823b1bbb06161ae32/src/policy/fees.cpp
@dataclass()
class SmartFeeEstimator:
    fee_tracker: FeeTracker
    max_block_cost_clvm: uint64
    log: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    def parse(self, fee_result: EstimateResult) -> float:
        fail_bucket: BucketResult = fee_result.fail_bucket
        median = fee_result.median

        if median != -1:
            return median

        if fail_bucket.start == 0:
            return -1.0

        # If median is -1, tracker wasn't able to find a passing bucket.
        # Suggest one bucket higher than the lowest failing bucket.

        # get_bucket_index returns left (-1) bucket (-1). Start value is already -1
        # We want +1 from the lowest bucket it failed at. Thus +3
        max_val = len(self.fee_tracker.buckets) - 1
        start_index = min(get_bucket_index(self.fee_tracker.buckets, fail_bucket.start) + 3, max_val)

        fee_val: float = self.fee_tracker.buckets[start_index]
        return fee_val / 1000.0

    def get_estimate_for_block(self, block: uint32) -> FeeEstimateV2:
        estimate_result = self.fee_tracker.estimate_fee_for_block(block)
        return self.estimate_result_to_fee_estimate(estimate_result)

    def get_estimate(self, time_offset_seconds: int) -> FeeEstimateV2:
        estimate_result = self.fee_tracker.estimate_fee(time_offset_seconds)
        return self.estimate_result_to_fee_estimate(estimate_result)

    def get_estimates(self, info: FeeMempoolInfo, ignore_mempool: bool = False) -> FeeEstimateGroup:
        self.log.error(self.fee_tracker.buckets)
        short_time_seconds, med_time_seconds, long_time_seconds = get_estimate_time_intervals()

        if ignore_mempool is False and (self.fee_tracker.latest_seen_height == 0):
            return FeeEstimateGroup(error="Not enough data", estimates=[])

        tracking_length = self.fee_tracker.latest_seen_height - self.fee_tracker.first_recorded_height
        if tracking_length < 20:
            return FeeEstimateGroup(error="Not enough data", estimates=[])

        if ignore_mempool is False and info.current_mempool_cost < int(info.mempool_info.max_block_clvm_cost * 0.8):
            return FeeEstimateGroup(
                error=None,
                estimates=[
                    FeeEstimate(None, uint64(short_time_seconds), FeeRate(uint64(0))),
                    FeeEstimate(None, uint64(med_time_seconds), FeeRate(uint64(0))),
                    FeeEstimate(None, uint64(long_time_seconds), FeeRate(uint64(0))),
                ],
            )

        short_result, med_result, long_result = self.fee_tracker.estimate_fees()

        short = self.estimate_result_to_fee_estimate(short_result)
        med = self.estimate_result_to_fee_estimate(med_result)
        long = self.estimate_result_to_fee_estimate(long_result)
        estimates = [fee_estimate_v2_to_v1(e) for e in [short, med, long]]
        return FeeEstimateGroup(error=None, estimates=estimates)

    def estimate_result_to_fee_estimate(self, r: EstimateResult) -> FeeEstimateV2:
        fee: float = self.parse(r)
        if fee == -1:
            return FeeEstimateV2("Not enough data", r.requested_time, FeeRateV2(0))
        else:
            # convert from mojo / 1000 clvm_cost to mojo / 1 clvm_cost
            return FeeEstimateV2(None, r.requested_time, FeeRateV2(fee / 1000))
