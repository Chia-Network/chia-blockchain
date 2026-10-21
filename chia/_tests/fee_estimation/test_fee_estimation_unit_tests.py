from __future__ import annotations

import logging

import pytest
from chia_rs.sized_ints import uint32, uint64

from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.fee_estimation import FeeBlockInfo, MempoolItemInfo
from chia.full_node.fee_estimator_constants import INFINITE_FEE_RATE, INITIAL_STEP, STORED_FEE_RATE_SCALE
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.fee_tracker import BucketResult, EstimateResult, get_bucket_index, init_buckets
from chia.protocols.fee_estimate import fee_rate_v2_to_v1
from chia.types.fee_rate import FeeRateV2
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
    height: uint32, num_tx: int, cost: uint64, fee: uint64, num_blocks_wait_in_mempool: int
) -> list[MempoolItemInfo]:
    block_included = uint32(height - num_blocks_wait_in_mempool)
    return [MempoolItemInfo(cost, fee, block_included)] * num_tx


def test_steady_fee_pressure() -> None:
    """
    We submit successive blocks containing transactions with identical FeeRates.
    We expect the estimator to converge on this FeeRate value.
    """
    max_block_cost_clvm = uint64(1000 * 1000)
    estimator = create_bitcoin_fee_estimator(max_block_cost_clvm)
    cost = uint64(5000000)
    fee = uint64(10000000)
    time_offset_seconds = 40
    num_blocks_wait_in_mempool = 5

    start = 100
    end = 300
    estimates_during = []
    start_from = 250
    for height in range(start, end):
        items = make_block(uint32(height), 1, cost, fee, num_blocks_wait_in_mempool)
        estimator.new_block(FeeBlockInfo(uint32(height), items))
        if height >= start_from:
            estimation = estimator.estimate_fee_rate(time_offset_seconds=time_offset_seconds * (height - start_from))
            estimates_during.append(estimation)

    estimates_after = []
    for height in range(start_from, end):
        estimation = estimator.estimate_fee_rate(time_offset_seconds=time_offset_seconds * (height - start_from))
        estimates_after.append(estimation)

    block_estimates = [estimator.estimate_fee_rate_for_block(uint32(h + 1)) for h in range(50)]
    for idx, es_after in enumerate(estimates_after):
        assert abs(es_after.mojos_per_clvm_cost - estimates_during[idx].mojos_per_clvm_cost) < 0.001
        assert es_after.mojos_per_clvm_cost == block_estimates[idx].mojos_per_clvm_cost
    # Index 10 asks about 400 seconds ahead. These blocks paid 2 mojos per cost.
    true_rate = fee / cost
    assert estimates_after[10].mojos_per_clvm_cost == pytest.approx(true_rate, rel=0.05)


def test_quote_uses_one_division() -> None:
    """A stored rate is mojos per STORED_FEE_RATE_SCALE cost. Publishing divides once."""
    assert STORED_FEE_RATE_SCALE == 1000
    estimator = create_bitcoin_fee_estimator(uint64(1_000_000))
    smart = estimator.fee_rate_estimator
    buckets = smart.fee_tracker.buckets
    empty = BucketResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    # A real rate of 5 is stored as 5,000. Five is also the full-mempool minimum.
    median_result = EstimateResult(uint64(40), empty, empty, 5 * STORED_FEE_RATE_SCALE)
    published = smart.estimate_result_to_fee_estimate(median_result)
    assert published.error is None
    assert published.estimated_fee_rate.mojos_per_clvm_cost == pytest.approx(5.0)
    send_xch_cost = 9_401_710
    assert int(published.estimated_fee_rate.mojos_per_clvm_cost * send_xch_cost) == 5 * send_xch_cost
    assert fee_rate_v2_to_v1(published.estimated_fee_rate).mojos_per_clvm_cost == 5

    # The wallet protocol still rounds a positive fraction up to 1 mojo per cost.
    fraction = smart.estimate_result_to_fee_estimate(
        EstimateResult(uint64(40), empty, empty, 0.2 * STORED_FEE_RATE_SCALE)
    )
    assert fraction.error is None
    assert fraction.estimated_fee_rate.mojos_per_clvm_cost == pytest.approx(0.2)
    assert fee_rate_v2_to_v1(fraction.estimated_fee_rate).mojos_per_clvm_cost == 1

    # The tracker records the edge below the failing bucket. The suggestion is one above it.
    failing_index = 5
    assert get_bucket_index(buckets, buckets[failing_index - 1]) + 3 == failing_index + 1
    fail_result = EstimateResult(
        uint64(40),
        empty,
        BucketResult(buckets[failing_index - 1], buckets[failing_index], 0.0, 0.0, 0.0, 0.0),
        -1.0,
    )
    published_fail = smart.estimate_result_to_fee_estimate(fail_result)
    assert published_fail.error is None
    assert published_fail.estimated_fee_rate.mojos_per_clvm_cost == pytest.approx(
        buckets[failing_index + 1] / STORED_FEE_RATE_SCALE
    )

    # start 0 is what the tracker writes when the first bucket fails.
    no_data = EstimateResult(uint64(40), empty, empty, -1.0)
    published_none = smart.estimate_result_to_fee_estimate(no_data)
    assert published_none.error == "Not enough data"
    assert published_none.estimated_fee_rate.mojos_per_clvm_cost == 0


def test_init_buckets() -> None:
    buckets = init_buckets()
    assert len(buckets) > 1
    assert buckets[0] == INITIAL_STEP
    assert buckets[-1] == INFINITE_FEE_RATE


def test_get_bucket_index_empty_buckets() -> None:
    buckets: list[float] = []
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
    inputs: list[list[float]]
    output: list[list[float]]
    inputs = [[], [-1], [0], [1], [0, 0], [0, 1], [1, 0], [1, 2, 3], [1, 1, 1], [3, 2, 1], [3, 3, 1], [1, 3, 3]]
    output = [[], [-1], [0], [1], [0, 0], [0, 0], [1, 0], [1, 1, 1], [1, 1, 1], [3, 2, 1], [3, 3, 1], [1, 1, 1]]
    i: list[float]
    o: list[float]
    for i, o in zip(inputs, output):
        print(o, i)
        assert o == make_monotonically_decreasing(i)
