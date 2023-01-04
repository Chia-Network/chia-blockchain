from __future__ import annotations

from typing import Dict

from chia_rs import Coin

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.fee_estimation import (
    EmptyFeeMempoolInfo,
    EmptyMempoolInfo,
    FeeBlockInfo,
    FeeMempoolInfo,
    MempoolInfo,
)
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.mempool import Mempool, MempoolRemoveReason
from chia.simulator.block_tools import test_constants
from chia.simulator.wallet_tools import WalletTool
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint32, uint64


def make_mempoolitem() -> MempoolItem:
    wallet_tool = WalletTool(test_constants)
    ph = wallet_tool.get_new_puzzlehash()
    coin = Coin(ph, ph, uint64(10000))
    spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)
    cost = uint64(5000000)
    block_height = 1

    fee = uint64(10000000)
    mempool_item = MempoolItem(
        spend_bundle,
        fee,
        NPCResult(None, None, cost),
        cost,
        spend_bundle.name(),
        [],
        uint32(block_height),
    )
    return mempool_item


class FeeEstimatorInterfaceIntegrationVerificationObject(FeeEstimatorInterface):
    add_mempool_item_called_count: int = 0
    remove_mempool_item_called_count: int = 0

    def new_block(self, block_info: FeeBlockInfo) -> None:
        """A new block has been added to the blockchain"""
        pass

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        """A MempoolItem (transaction and associated info) has been added to the mempool"""
        self.add_mempool_item_called_count += 1

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItem) -> None:
        """A MempoolItem (transaction and associated info) has been removed from the mempool"""
        self.remove_mempool_item_called_count += 1

    def estimate_fee_rate(self, *, time_offset_seconds: int) -> FeeRate:
        """time_offset_seconds: number of seconds into the future for which to estimate fee"""
        return FeeRate(uint64(0))

    def mempool_size(self) -> CLVMCost:
        """Report last seen mempool size"""
        return CLVMCost(uint64(0))

    def mempool_max_size(self) -> CLVMCost:
        """Report current mempool max "size" (i.e. CLVM cost)"""
        return CLVMCost(uint64(0))

    def get_mempool_info(self) -> FeeMempoolInfo:
        """Report Mempool current configuration and state"""
        return EmptyFeeMempoolInfo


def test_mempool_fee_estimator_init() -> None:
    max_block_cost = uint64(1000 * 1000)
    fee_estimator = create_bitcoin_fee_estimator(max_block_cost)
    mempool = Mempool(EmptyMempoolInfo, fee_estimator)
    assert mempool.fee_estimator


test_mempool_info = MempoolInfo(
    max_size_in_cost=CLVMCost(uint64(5000000)),
    minimum_fee_per_cost_to_replace=FeeRate(uint64(5)),
    max_block_clvm_cost=CLVMCost(uint64(1000000)),
)


def test_mempool_fee_estimator_add_item() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    item = make_mempoolitem()
    mempool.add_to_pool(item, block_height=uint32(1))
    assert mempool.fee_estimator.add_mempool_item_called_count == 1  # type: ignore[attr-defined]


def test_item_not_removed_if_not_added() -> None:
    for reason in MempoolRemoveReason:
        fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
        mempool = Mempool(test_mempool_info, fee_estimator)
        item = make_mempoolitem()
        mempool.remove_from_pool([item.name], reason, block_height=uint32(1))
        assert mempool.fee_estimator.remove_mempool_item_called_count == 0  # type: ignore[attr-defined]


def test_mempool_fee_estimator_remove_item() -> None:
    should_call_fee_estimator_remove: Dict[MempoolRemoveReason, int] = {
        MempoolRemoveReason.BLOCK_INCLUSION: 0,
        MempoolRemoveReason.CONFLICT: 1,
        MempoolRemoveReason.POOL_FULL: 1,
    }
    for reason, call_count in should_call_fee_estimator_remove.items():
        fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
        mempool = Mempool(test_mempool_info, fee_estimator)
        item = make_mempoolitem()
        mempool.add_to_pool(item, block_height=uint32(1))
        mempool.remove_from_pool([item.name], reason, block_height=uint32(1))
        assert mempool.fee_estimator.remove_mempool_item_called_count == call_count  # type: ignore[attr-defined]


def test_mempool_manager_fee_estimator_new_block() -> None:
    pass
