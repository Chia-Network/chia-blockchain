import abc

from chia.policy.fee_estimation import FeeBlockInfo, FeeMempoolInfo


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


# We inherit only to enforce the interface, not to share behaviour
class FeeEstimatorInterface(abc.ABC):
    @abc.abstractmethod
    def new_block(self, block_info: FeeBlockInfo):
        pass

    @abc.abstractmethod
    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo):
        pass

    @abc.abstractmethod
    def remove_mempool_item(self, mempool_item_info: FeeMempoolInfo):
        pass

    @abc.abstractmethod
    def estimate_fee(self, cost: int, time: int):
        pass

