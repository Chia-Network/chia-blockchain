from __future__ import annotations

import types
from typing import Dict, List

import pytest
from chia_rs import Coin

from chia._tests.core.mempool.test_mempool_manager import (
    create_test_block_record,
    instantiate_mempool_manager,
    zero_calls_get_coin_records,
)
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.fee_estimation import (
    EmptyFeeMempoolInfo,
    EmptyMempoolInfo,
    FeeBlockInfo,
    FeeMempoolInfo,
    MempoolInfo,
    MempoolItemInfo,
)
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.fee_tracker import FeeTracker
from chia.full_node.mempool import Mempool, MempoolRemoveReason
from chia.simulator.block_tools import test_constants
from chia.simulator.wallet_tools import WalletTool
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate, FeeRateV2
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle_conditions import Spend, SpendBundleConditions
from chia.util.ints import uint32, uint64


def make_mempoolitem() -> MempoolItem:
    wallet_tool = WalletTool(test_constants)
    ph = wallet_tool.get_new_puzzlehash()
    coin = Coin(ph, ph, uint64(10000))
    spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)
    cost = uint64(1000000)
    block_height = 1

    fee = uint64(10000000)
    spends: List[Spend] = []
    conds = SpendBundleConditions(spends, 0, 0, 0, None, None, [], cost, 0, 0)
    mempool_item = MempoolItem(
        spend_bundle,
        fee,
        NPCResult(None, conds),
        spend_bundle.name(),
        uint32(block_height),
    )
    return mempool_item


class FeeEstimatorInterfaceIntegrationVerificationObject(FeeEstimatorInterface):
    add_mempool_item_called_count: int = 0
    remove_mempool_item_called_count: int = 0
    new_block_called_count: int = 0
    current_block_height: int = 0

    def new_block_height(self, block_height: uint32) -> None:
        self.current_block_height: int = block_height

    def new_block(self, block_info: FeeBlockInfo) -> None:
        """A new block has been added to the blockchain"""
        self.current_block_height = block_info.block_height
        self.new_block_called_count += 1

    def add_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItemInfo) -> None:
        """A MempoolItem (transaction and associated info) has been added to the mempool"""
        self.add_mempool_item_called_count += 1

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItemInfo) -> None:
        """A MempoolItem (transaction and associated info) has been removed from the mempool"""
        self.remove_mempool_item_called_count += 1

    def estimate_fee_rate(self, *, time_offset_seconds: int) -> FeeRateV2:
        """time_offset_seconds: number of seconds into the future for which to estimate fee"""
        return FeeRateV2(0)

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
    mempool.add_to_pool(item)
    assert mempool.fee_estimator.add_mempool_item_called_count == 1  # type: ignore[attr-defined]


def test_item_not_removed_if_not_added() -> None:
    for reason in MempoolRemoveReason:
        fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
        mempool = Mempool(test_mempool_info, fee_estimator)
        item = make_mempoolitem()
        with pytest.raises(KeyError):
            mempool.remove_from_pool([item.name], reason)
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
        mempool.add_to_pool(item)
        mempool.remove_from_pool([item.name], reason)
        assert mempool.fee_estimator.remove_mempool_item_called_count == call_count  # type: ignore[attr-defined]


def test_mempool_manager_fee_estimator_new_block() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    item = make_mempoolitem()
    height = uint32(4)
    included_items = [MempoolItemInfo(item.cost, item.fee, item.height_added_to_mempool)]
    mempool.fee_estimator.new_block(FeeBlockInfo(height, included_items))
    assert mempool.fee_estimator.new_block_called_count == 1  # type: ignore[attr-defined]


def test_current_block_height_init() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    assert mempool.fee_estimator.current_block_height == uint32(0)  # type: ignore[attr-defined]


def test_current_block_height_add() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    item = make_mempoolitem()
    height = uint32(7)
    fee_estimator.new_block_height(height)
    mempool.add_to_pool(item)
    assert mempool.fee_estimator.current_block_height == height  # type: ignore[attr-defined]


def test_current_block_height_remove() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    item = make_mempoolitem()
    height = uint32(8)
    fee_estimator.new_block_height(height)
    mempool.add_to_pool(item)
    mempool.remove_from_pool([item.name], MempoolRemoveReason.CONFLICT)
    assert mempool.fee_estimator.current_block_height == height  # type: ignore[attr-defined]


def test_current_block_height_new_block_height() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    height = uint32(9)
    mempool.fee_estimator.new_block_height(height)
    assert mempool.fee_estimator.current_block_height == height  # type: ignore[attr-defined]


def test_current_block_height_new_block() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    height = uint32(10)
    included_items: List[MempoolItemInfo] = []
    mempool.fee_estimator.new_block(FeeBlockInfo(height, included_items))
    assert mempool.fee_estimator.current_block_height == height  # type: ignore[attr-defined]


def test_current_block_height_new_height_then_new_block() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    height = uint32(11)
    included_items: List[MempoolItemInfo] = []
    fee_estimator.new_block_height(uint32(height - 1))
    mempool.fee_estimator.new_block(FeeBlockInfo(height, included_items))
    assert mempool.fee_estimator.current_block_height == height  # type: ignore[attr-defined]


def test_current_block_height_new_block_then_new_height() -> None:
    fee_estimator = FeeEstimatorInterfaceIntegrationVerificationObject()
    mempool = Mempool(test_mempool_info, fee_estimator)
    height = uint32(12)
    included_items: List[MempoolItemInfo] = []
    fee_estimator.new_block_height(uint32(height - 1))
    mempool.fee_estimator.new_block(FeeBlockInfo(height, included_items))
    fee_estimator.new_block_height(uint32(height + 1))
    assert mempool.fee_estimator.current_block_height == height + 1  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_mm_new_peak_changes_fee_estimator_block_height() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    block2 = create_test_block_record(height=uint32(2))
    await mempool_manager.new_peak(block2, None)
    assert mempool_manager.mempool.fee_estimator.block_height == uint32(2)  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_mm_calls_new_block_height() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    new_block_height_called = False

    def test_new_block_height_called(self: FeeEstimatorInterface, height: uint32) -> None:
        nonlocal new_block_height_called
        new_block_height_called = True

    # Replace new_block_height with test function
    mempool_manager.fee_estimator.new_block_height = types.MethodType(  # type: ignore[method-assign]
        test_new_block_height_called, mempool_manager.fee_estimator
    )
    block2 = create_test_block_record(height=uint32(2))
    await mempool_manager.new_peak(block2, None)
    assert new_block_height_called


def test_add_tx_called() -> None:
    max_block_cost = uint64(1000 * 1000)
    fee_estimator = create_bitcoin_fee_estimator(max_block_cost)
    mempool = Mempool(test_mempool_info, fee_estimator)
    item = make_mempoolitem()

    add_tx_called = False

    def add_tx_called_fun(self: FeeTracker, mitem: MempoolItem) -> None:
        nonlocal add_tx_called
        add_tx_called = True

    # Replace with test method
    mempool.fee_estimator.tracker.add_tx = types.MethodType(  # type: ignore[attr-defined]
        add_tx_called_fun, mempool.fee_estimator.tracker  # type: ignore[attr-defined]
    )

    mempool.add_to_pool(item)

    assert add_tx_called
