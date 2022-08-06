from typing_extensions import Protocol

from chia.policy.fee_estimation import FeeBlockInfo, FeeMempoolInfo
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64


class FeeEstimatorConfig:
    """
    Holds configuration values used to tune FeeEstimator. Can Vary per Estimator.

    blockchain_time_window  # seconds into the past to consider historical blockchain data
    """


class FeeEstimatorInterface(Protocol):
    def new_block(self, block_info: FeeBlockInfo) -> None:
        pass

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def estimate_fee(self, *, cost: int, time: int) -> uint64:
        pass

    def mempool_size(self) -> uint64:
        pass

    def mempool_max_size(self) -> uint64:
        pass
