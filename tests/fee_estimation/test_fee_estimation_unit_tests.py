from __future__ import annotations

import logging
from typing import List

import pytest
from chia_rs import Coin

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.fee_estimation import FeeBlockInfo
from chia.full_node.fee_estimator_constants import INFINITE_FEE_RATE, INITIAL_STEP
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.fee_tracker import get_bucket_index, init_buckets
from chia.simulator.block_tools import test_constants
from chia.simulator.wallet_tools import WalletTool
from chia.types.fee_rate import FeeRateV2
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint32, uint64
from chia.util.math import make_monotonically_decreasing

log = logging.getLogger(__name__)


def test_interface() -> None:
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator: FeeEstimatorInterface = create_bitcoin_fee_estimator(max_block_cost_clvm)
    target_times = [0, 120, 300]
    estimates = [estimator.estimate_fee_rate(time_offset_seconds=time) for time in target_times]
    current_fee_rate = estimator.estimate_fee_rate(
        time_offset_seconds=1,
    )
    zero = FeeRateV2(0)
    assert estimates == [zero, zero, zero]
    assert current_fee_rate.mojos_per_clvm_cost == 0


def test_estimator_create() -> None:
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator = create_bitcoin_fee_estimator(max_block_cost_clvm)
    assert estimator is not None


def test_single_estimate() -> None:
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator = create_bitcoin_fee_estimator(max_block_cost_clvm)
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
    estimator = create_bitcoin_fee_estimator(max_block_cost_clvm)
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

    # est = estimator.estimate_fee_rate(time_offset_seconds=240) #TODO
    e = []

    for seconds in range(30, 5 * 60, 30):
        est2 = estimator.estimate_fee_rate(time_offset_seconds=seconds)
        e.append(est2)

    # assert est == FeeRate.create(Mojos(fee), CLVMCost(cost)) #TODO
    estimates_after = [estimator.estimate_fee_rate(time_offset_seconds=40 * height) for height in range(start, end)]
    block_estimates = [estimator.estimate_fee_rate_for_block(uint32(h)) for h in range(start, end)]

    assert estimates_during == estimates_after
    assert estimates_after == block_estimates


def test_init_buckets() -> None:
    buckets = init_buckets()
    assert len(buckets) > 1
    assert buckets[0] == INITIAL_STEP
    assert buckets[-1] == INFINITE_FEE_RATE


def test_get_bucket_index_empty_buckets() -> None:
    buckets: List[float] = []
    for rate in [0.5, 1.0, 2.0]:
        with pytest.raises(RuntimeError):
            a = get_bucket_index(buckets, rate)
            log.warning(a)


def test_get_bucket_index_fee_rate_too_high() -> None:
    buckets = [0.5, 1.0, 2.0]
    index = get_bucket_index(buckets, 3.0)
    assert index == len(buckets) - 1


def test_get_bucket_index_single_entry() -> None:
    """Test single entry with low, equal and high keys"""
    from sys import float_info

    e = float_info.epsilon * 10
    buckets = [1.0]
    print()
    print(buckets)
    for rate, expected_index in ((0.5, 0), (1.0 - e, 0), (1.5, 0)):
        result_index = get_bucket_index(buckets, rate)
        print(rate, expected_index, result_index)
        assert expected_index == result_index


def test_get_bucket_index() -> None:
    from sys import float_info

    e = float_info.epsilon * 10
    buckets = [1.0, 2.0]

    for rate, expected_index in ((0.5, 0), (1.0 - e, 0), (1.5, 0), (2.0 - e, 0), (2.0 + e, 1), (2.1, 1)):
        result_index = get_bucket_index(buckets, rate)
        assert result_index == expected_index


def test_monotonically_decrease() -> None:
    inputs: List[List[float]]
    output: List[List[float]]
    inputs = [[], [-1], [0], [1], [0, 0], [0, 1], [1, 0], [1, 2, 3], [1, 1, 1], [3, 2, 1], [3, 3, 1], [1, 3, 3]]
    output = [[], [-1], [0], [1], [0, 0], [0, 0], [1, 0], [1, 1, 1], [1, 1, 1], [3, 2, 1], [3, 3, 1], [1, 1, 1]]
    i: List[float]
    o: List[float]
    for i, o in zip(inputs, output):
        print(o, i)
        assert o == make_monotonically_decreasing(i)
