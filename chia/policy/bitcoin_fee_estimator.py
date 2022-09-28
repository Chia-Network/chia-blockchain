import logging
from datetime import datetime
from typing import Any, Dict, List

from chia.full_node.fee_estimate_store import FeeStore
from chia.full_node.fee_estimator import SmartFeeEstimator
from chia.full_node.fee_tracker import FeeTracker
from chia.policy.fee_estimation import FeeMempoolInfo
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.types.mojos import Mojos
from chia.util.ints import uint32, uint64

MIN_MOJO_PER_COST = 5


def demo_fee_rate_function(cost: int, time_in_seconds: int) -> uint64:
    return uint64(cost * MIN_MOJO_PER_COST * max((3600 - time_in_seconds), 1))


class BitcoinFeeEstimator:  # FeeEstimatorInterface Protocol
    def __init__(self, config: Dict[str, Any]) -> None:
        self.fee_rate_estimator: SmartFeeEstimator = config["estimator"]
        self.tracker: FeeTracker = config["tracker"]
        self.last_mempool_info = FeeMempoolInfo(
            CLVMCost(uint64(0)),
            FeeRate.create(Mojos(uint64(0)), CLVMCost(uint64(1))),
            CLVMCost(uint64(0)),
            datetime.min,
            CLVMCost(uint64(0)),
        )

    def new_block(self, block_height: uint32, included_items: List[MempoolItem]) -> None:
        self.tracker.process_block(block_height, included_items)

    def add_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        self.last_mempool_info = mempool_info

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        pass

    def estimate_fee_rate(self, *, time_delta_seconds: int) -> FeeRate:
        """
        cost: SpendBundle clvm_cost
        time_delta_seconds: Target time in the future we want our tx included by
        """
        fee_estimate = self.fee_rate_estimator.get_estimate(time_delta_seconds)
        return fee_estimate.estimated_fee_rate

    def estimate_fee_rate_for_block(self, block: uint32) -> FeeRate:
        fee_estimate = self.fee_rate_estimator.get_estimate_for_block(block)
        return fee_estimate.estimated_fee_rate
        # xxx if fee_estimate.error: return None

    def mempool_size(self) -> CLVMCost:
        """Report last seen mempool size"""
        return self.last_mempool_info.current_mempool_cost

    def mempool_max_size(self) -> CLVMCost:
        """Report current mempool max size (cost)"""
        return self.last_mempool_info.max_size_in_cost


def create_bitcoin_fee_estimator(max_block_cost_clvm: uint64, log: logging.Logger) -> BitcoinFeeEstimator:
    # fee_store and fee_tracker are particular to the BitcoinFeeEstimator, and
    # are not necessary if a different fee estimator is used.
    fee_store = FeeStore()
    fee_tracker = FeeTracker(log, fee_store)
    smart_fee_estimator = SmartFeeEstimator(fee_tracker, max_block_cost_clvm)
    config = {
        "tracker": fee_tracker,
        "estimator": smart_fee_estimator,
        "store": fee_store,
        "max_block_cost_clvm": max_block_cost_clvm,
    }
    return BitcoinFeeEstimator(config)
