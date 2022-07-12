from chia.policy.fee_estimation import FeeBlockInfo, FeeMempoolInfo
from chia.policy.fee_estimator import FeeEstimatorConfig
from chia.util.ints import uint64

MIN_MOJO_PER_COST = 5


def demo_fee_rate_function(cost: int, time_in_seconds: int):
    return uint64(cost * (MIN_MOJO_PER_COST + time_in_seconds))


class FeeEstimatorDemo:  # FeeEstimatorInterface Protocol
    def __init__(self, config: FeeEstimatorConfig) -> None:
        self.config = config

    def new_block(self, block_info: FeeBlockInfo) -> None:
        pass

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo) -> None:
        pass

    def remove_mempool_item(self, mempool_item_info: FeeMempoolInfo) -> None:
        pass

    def estimate_fee(self, cost: int, time: int) -> uint64:
        return demo_fee_rate_function(cost, time)
