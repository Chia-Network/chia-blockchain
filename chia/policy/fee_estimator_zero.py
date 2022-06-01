from chia.policy.fee_estimation import FeeMempoolInfo, FeeBlockInfo
from chia.policy.fee_estimator import FeeEstimatorInterface
from chia.util.ints import uint64


class FeeEstimatorZero(FeeEstimatorInterface):
    def __init__(self, config):
        self.config = config

    def new_block(self, block_info: FeeBlockInfo):
        pass

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo):
        pass

    def remove_mempool_item(self, mempool_item_info: FeeMempoolInfo):
        pass

    def estimate_fee(self, cost: int, time: int) -> uint64:
        return 0
