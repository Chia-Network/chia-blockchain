from typing import List

from chia.full_node.fee_estimate import FeeEstimate
from chia.util.ints import uint64

MIN_MOJO_PER_COST = 5


def demo_fee_rate_function(cost: int, time_in_seconds: int) -> uint64:
    return uint64(cost * MIN_MOJO_PER_COST * max((3600 - time_in_seconds), 1))


class FeeEstimatorDemo:  # FeeEstimatorInterface Protocol
    def estimate_fee(self, *, cost: int, time: int) -> uint64:
        return demo_fee_rate_function(cost, time)

    def request_fee_estimates(self, request_times: List[uint64]) -> List[FeeEstimate]:
        estimates = [self.estimate_fee(cost=1, time=t) for t in request_times]
        fee_estimates = [FeeEstimate(t, e) for (t, e) in zip(request_times, estimates)]
        return fee_estimates
