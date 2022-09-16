from datetime import datetime
from typing import Dict, Any, List

from chia.consensus.block_record import BlockRecord
from chia.full_node.fee_estimator import SmartFeeEstimator
from chia.full_node.fee_tracker import FeeTracker
from chia.policy.fee_estimation import FeeMempoolInfo
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64, uint32

MIN_MOJO_PER_COST = 5


def demo_fee_rate_function(cost: int, time_in_seconds: int) -> uint64:
    return uint64(cost * MIN_MOJO_PER_COST * max((3600 - time_in_seconds), 1))


class BitcoinFeeEstimator:  # FeeEstimatorInterface Protocol
    def __init__(self, config: Dict[str, Any]) -> None:
        # TODO: remove mempool_manager from passed-in config
        self.estimator: SmartFeeEstimator = config["estimator"]
        self.tracker: FeeTracker = config["tracker"]
        self.last_mempool_info = FeeMempoolInfo(uint64(0), uint64(0), uint64(0), datetime.min, uint64(0))

    def new_block(self, block_info: BlockRecord, included_items: List[MempoolItem]) -> None:
        self.tracker.process_block(block_info.height, included_items)

    def add_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        self.last_mempool_info = mempool_info

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def estimate_fee(self, *, cost: int, time_delta_seconds: int) -> uint64: #xxx cost, delta secs
        """cost: SpendBundle cost"""
        fee_estimate = self.estimator.get_estimate(time_delta_seconds)
        return fee_estimate.estimated_fee

    def estimate_fee_for_block(self, block: uint32) -> uint64:
        fee_estimate = self.estimator.get_estimate_for_block(block)
        return fee_estimate.estimated_fee # if fee_estimate.error: return None

    def mempool_size(self) -> uint64:
        """Report last seen mempool size"""
        return self.last_mempool_info.current_mempool_cost

    def mempool_max_size(self) -> uint64:
        """Report current mempool max size (cost)"""
        return self.last_mempool_info.max_size_in_cost
