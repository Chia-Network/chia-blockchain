from chia.policy.fee_estimation import FeeBlockInfo, FeeMempoolInfo
from chia.policy.fee_estimator import FeeEstimatorConfig
from chia.util.ints import uint64


class FeeEstimatorZero:  # FeeEstimatorInterface Protocol
    def __init__(self, config: FeeEstimatorConfig) -> None:
        self.config = config

    def new_block(self, block_info: FeeBlockInfo) -> None:
        pass

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo) -> None:
        pass

    def remove_mempool_item(self, mempool_item_info: FeeMempoolInfo) -> None:
        pass

    def estimate_fee(self, cost: int, time: int) -> uint64:
        return uint64(0)
