from typing import List

from typing_extensions import Protocol

from chia.policy.fee_estimation import FeeMempoolInfo
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64, uint32


class FeeEstimatorConfig:
    """
    Holds configuration values used to tune FeeEstimator. Can Vary per Estimator.

    blockchain_time_window  # seconds into the past to consider historical blockchain data
    """


class FeeEstimatorInterface(Protocol):
    #def new_block(self, block_info: FeeBlockInfo) -> None:
    def new_block(self, block_height: uint32, included_items: List[MempoolItem]) -> None:
        pass

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def estimate_fee_rate(self, *, time_delta_seconds: int) -> FeeRate:
        """time_delta_seconds: number of seconds into the future for which to estimate fee"""
        pass

    def mempool_size(self) -> CLVMCost:
        pass

    def mempool_max_size(self) -> CLVMCost:
        pass
