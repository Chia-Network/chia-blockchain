from typing_extensions import Protocol

from chia.policy.fee_estimation import FeeBlockInfo, FeeMempoolInfo
from chia.util.ints import uint64


class FeeEstimatorConfig:
    """
    Holds configuration values used to tune FeeEstimator


    mempool
    self.max_size_in_cost: int = max_size_in_cost
    self.total_mempool_cost: int = 0
    get_min_fee_rate
    blockchain_time_window  # seconds into the past to consider historical blockchain data
    """


class MempoolState:
    """Minimum information needed to mirror state of the mempool for values we are concerned with"""

    total_mempool_cost: int
    min_fee_rate: float


class FeeEstimatorInterface(Protocol):
    def new_block(self, block_info: FeeBlockInfo) -> None:
        pass

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo) -> None:
        pass

    def remove_mempool_item(self, mempool_item_info: FeeMempoolInfo) -> None:
        pass

    def estimate_fee(self, cost: int, time: int) -> uint64:
        pass
