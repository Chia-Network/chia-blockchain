from __future__ import annotations

import logging
from typing import List

from chia_rs import Coin

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.fee_estimation import FeeBlockInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.simulator.block_tools import test_constants
from chia.simulator.wallet_tools import WalletTool
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.types.mojos import Mojos
from chia.util.ints import uint32, uint64

log = logging.getLogger(__name__)


def test_interface() -> None:
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator: FeeEstimatorInterface = create_bitcoin_fee_estimator(max_block_cost_clvm, log)
    target_times = [0, 120, 300]
    estimates = [estimator.estimate_fee_rate(time_offset_seconds=time) for time in target_times]
    current_fee_rate = estimator.estimate_fee_rate(
        time_offset_seconds=1,
    )
    zero = FeeRate(uint64(0))
    assert estimates == [zero, zero, zero]
    assert current_fee_rate.mojos_per_clvm_cost == 0


def test_estimator_create() -> None:
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator = create_bitcoin_fee_estimator(max_block_cost_clvm, log)
    assert estimator is not None


def test_single_estimate() -> None:
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator = create_bitcoin_fee_estimator(max_block_cost_clvm, log)
    height = uint32(1)
    estimator.new_block(FeeBlockInfo(height, []))
    fee_rate = estimator.estimate_fee_rate(time_offset_seconds=40 * height)
    assert fee_rate.mojos_per_clvm_cost == 0


def make_block(
    wallet_tool: WalletTool, height: uint32, num_tx: int, cost: uint64, fee: uint64, num_blocks_wait_in_mempool: int
) -> List[MempoolItem]:
    items = []
    ph = wallet_tool.get_new_puzzlehash()
    coin = Coin(ph, ph, uint64(10000))
    spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)

    for n in range(num_tx):
        block_included = uint32(height - num_blocks_wait_in_mempool)
        mempool_item = MempoolItem(
            spend_bundle, fee, NPCResult(None, None, cost), cost, spend_bundle.name(), [], block_included
        )
        items.append(mempool_item)
    return items


def test_steady_fee_pressure() -> None:
    """
    We submit successive blocks containing transactions with identical FeeRates.
    We expect the estimator to converge on this FeeRate value.
    """
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator = create_bitcoin_fee_estimator(max_block_cost_clvm, log)
    wallet_tool = WalletTool(test_constants)
    cost = uint64(5000000)
    fee = uint64(10000000)
    num_blocks_wait_in_mempool = 5

    start = 100
    end = 300
    estimates_during = []
    for height in range(start, end):
        height = uint32(height)
        items = make_block(wallet_tool, height, 1, cost, fee, num_blocks_wait_in_mempool)
        estimator.new_block(FeeBlockInfo(uint32(height), items))
        estimates_during.append(estimator.estimate_fee_rate(time_offset_seconds=40 * height))

    est = estimator.estimate_fee_rate(time_offset_seconds=240)
    e = []

    for seconds in range(30, 5 * 60, 30):
        est2 = estimator.estimate_fee_rate(time_offset_seconds=seconds)
        e.append(est2)

    assert est == FeeRate.create(Mojos(fee), CLVMCost(cost))
    estimates_after = [estimator.estimate_fee_rate(time_offset_seconds=40 * height) for height in range(start, end)]
    block_estimates = [estimator.estimate_fee_rate_for_block(uint32(h)) for h in range(start, end)]

    assert estimates_during == estimates_after
    assert estimates_after == block_estimates


def test_fee_estimation_inception() -> None:
    """
    Confirm that estimates are given only for blocks farther out than the smallest
    transaction block wait time we have observed.
    """
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator1 = create_bitcoin_fee_estimator(max_block_cost_clvm, log)
    wallet_tool = WalletTool(test_constants)
    cost = uint64(5000000)
    fee = uint64(10000000)

    start = 100
    end = 300

    for height in range(start, end):
        height = uint32(height)
        # Transactions will wait in the mempool for 1 block
        items = make_block(wallet_tool, height, 1, cost, fee, num_blocks_wait_in_mempool=1)
        estimator1.new_block(FeeBlockInfo(uint32(height), items))

    e = []
    for seconds in range(40, 5 * 60, 40):
        est = estimator1.estimate_fee_rate(time_offset_seconds=seconds)
        e.append(est.mojos_per_clvm_cost)

    # Confirm that estimates are available for near blocks
    assert e == [2, 2, 2, 2, 2, 2, 2]

    ##########################################################
    estimator5 = create_bitcoin_fee_estimator(max_block_cost_clvm, log)

    for height in range(start, end):
        height = uint32(height)
        # Transactions will wait in the mempool for 5 blocks
        items = make_block(wallet_tool, height, 1, cost, fee, num_blocks_wait_in_mempool=5)
        estimator5.new_block(FeeBlockInfo(uint32(height), items))

    e1 = []
    for seconds in range(40, 5 * 60, 40):
        est = estimator5.estimate_fee_rate(time_offset_seconds=seconds)
        e1.append(est.mojos_per_clvm_cost)

    # Confirm that estimates start after block 4
    assert e1 == [0, 0, 0, 2, 2, 2, 2]
