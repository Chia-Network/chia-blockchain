from __future__ import annotations

from typing import Any, Dict, List

from chia.full_node.fee_estimate import FeeEstimateV2
from chia.full_node.fee_estimation import FeeBlockInfo, FeeMempoolInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRateV2
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64

MIN_MOJO_PER_COST = 5


def example_fee_rate_function(time_in_seconds: int) -> float:
    return MIN_MOJO_PER_COST * max((3600 - time_in_seconds), 1)


class FeeEstimatorExample(FeeEstimatorInterface):
    """
    An example Fee Estimator that can be plugged in for testing, or development of new fee estimators.

    Note that we inherit from the FeeEstimatorInterface protocol to ensure we keep
    up to date with interface changes.
    """

    def __init__(self, config: Dict[str, Any] = {}) -> None:
        self.config = config

    def new_block(self, block_info: FeeBlockInfo) -> None:
        pass

    def add_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def estimate_fee_rate(self, *, time_offset_seconds: int) -> FeeRateV2:
        return FeeRateV2(example_fee_rate_function(time_offset_seconds))

    def mempool_size(self) -> CLVMCost:
        """Report last seen mempool size"""
        return CLVMCost(uint64(0))

    def mempool_max_size(self) -> CLVMCost:
        """Report current mempool max size (cost)"""
        return CLVMCost(uint64(0))

    def request_fee_estimates(self, request_times: List[uint64]) -> List[FeeEstimateV2]:
        estimates = [self.estimate_fee_rate(time_offset_seconds=t) for t in request_times]
        fee_estimates = [FeeEstimateV2(None, t, e) for (t, e) in zip(request_times, estimates)]
        return fee_estimates
