from __future__ import annotations

import logging
from datetime import datetime

from chia.full_node.fee_estimate_store import FeeStore
from chia.full_node.fee_estimation import FeeBlockInfo, FeeMempoolInfo
from chia.full_node.fee_estimator import SmartFeeEstimator
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.fee_tracker import FeeTracker
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.types.mojos import Mojos
from chia.util.ints import uint32, uint64

log = logging.getLogger(__name__)


class BitcoinFeeEstimator(FeeEstimatorInterface):
    """
    A Fee Estimator based on the concepts and code at:
    https://github.com/bitcoin/bitcoin/tree/5b6f0f31fa6ce85db3fb7f9823b1bbb06161ae32/src/policy
    """

    def __init__(
        self, fee_tracker: FeeTracker, smart_fee_estimator: SmartFeeEstimator, mempool_info: FeeMempoolInfo
    ) -> None:
        self.fee_rate_estimator: SmartFeeEstimator = smart_fee_estimator
        self.tracker: FeeTracker = fee_tracker
        self.last_mempool_info: FeeMempoolInfo = mempool_info

    def new_block(self, block_info: FeeBlockInfo) -> None:
        # log.warning(f"m_fee_rate_avg: {self.tracker.short_horizon.m_fee_rate_avg}")
        # log.warning(f"confirmed_average: {self.tracker.short_horizon.confirmed_average}")
        # log.warning(f"failed_average: {self.tracker.short_horizon.failed_average}")

        # log.warning(f"unconfirmed_txs: {self.tracker.short_horizon.unconfirmed_txs}")
        # log.warning(f"sorted_buckets: {self.tracker.short_horizon.sorted_buckets}")
        log.warning(f"new_block: short {self.tracker.short_horizon}")
        log.warning(f"new_block: med   {self.tracker.med_horizon}")
        log.warning(f"new_block: long  {self.tracker.long_horizon}")
        # if len(block_info.included_items) > 0:
        #    breakpoint()
        self.tracker.process_block(block_info.block_height, block_info.included_items)

    def add_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        self.last_mempool_info = mempool_info
        self.tracker.add_tx(mempool_item)

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        self.last_mempool_info = mempool_info
        self.tracker.remove_tx(mempool_item)

    def estimate_fee_rate(self, *, time_offset_seconds: int) -> FeeRate:
        """
        time_offset_seconds: Target time in the future we want our tx included by
        """
        fee_estimate = self.fee_rate_estimator.get_estimate(time_offset_seconds)
        if fee_estimate.error is not None:
            return FeeRate(uint64(0))
        return fee_estimate.estimated_fee_rate

    def estimate_fee_rate_for_block(self, block: uint32) -> FeeRate:
        fee_estimate = self.fee_rate_estimator.get_estimate_for_block(block)
        if fee_estimate.error is not None:
            return FeeRate(uint64(0))
        return fee_estimate.estimated_fee_rate

    def mempool_size(self) -> CLVMCost:
        """Report last seen mempool size"""
        return self.last_mempool_info.current_mempool_cost

    def mempool_max_size(self) -> CLVMCost:
        """Report current mempool max size (cost)"""
        return self.last_mempool_info.max_size_in_cost

    def get_tracker(self) -> FeeTracker:
        """
        `get_tracker` is for testing the BitcoinFeeEstimator.
        Not part of `FeeEstimatorInterface`
        """
        return self.tracker


def create_bitcoin_fee_estimator(
    max_mempool_cost: uint64, max_block_cost_clvm: uint64, minimum_replace_fpc: FeeRate
) -> BitcoinFeeEstimator:
    # fee_store and fee_tracker are particular to the BitcoinFeeEstimator, and
    # are not necessary if a different fee estimator is used.
    fee_store = FeeStore()
    fee_tracker = FeeTracker(fee_store)
    smart_fee_estimator = SmartFeeEstimator(fee_tracker, max_block_cost_clvm)
    mempool_info = FeeMempoolInfo(
        CLVMCost(uint64(max_mempool_cost)),
        CLVMCost(max_block_cost_clvm),
        minimum_replace_fpc,  # nonzero_fee_minimum_fpc
        CLVMCost(uint64(0)),  # total_mempool_cost
        Mojos(uint64(0)),  # total_mempool_fees
        datetime.now(),
    )
    return BitcoinFeeEstimator(fee_tracker, smart_fee_estimator, mempool_info)
