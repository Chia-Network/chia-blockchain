from __future__ import annotations

from random import Random

import pytest
from chia_rs.sized_ints import uint32, uint64

from chia._tests.core.consensus.test_pot_iterations import test_constants
from chia._tests.util.db_connection import DBConnection
from chia.full_node.bitcoin_fee_estimator import BitcoinFeeEstimator
from chia.full_node.coin_store import CoinStore
from chia.full_node.fee_estimate_store import FeeStore
from chia.full_node.fee_estimation import MempoolItemInfo
from chia.full_node.fee_estimator import SmartFeeEstimator
from chia.full_node.fee_estimator_constants import STORED_FEE_RATE_SCALE, SUCCESS_PCT, SUFFICIENT_FEE_TXS
from chia.full_node.fee_tracker import FeeStat, FeeTracker
from chia.full_node.mempool_manager import MempoolManager
from chia.util.inline_executor import InlineExecutor


@pytest.mark.anyio
async def test_basics() -> None:
    fee_store = FeeStore()
    fee_tracker = FeeTracker(fee_store)

    cost = uint64(5000000)
    for i in range(300, 700):
        items = []
        for _ in range(2, 100):
            fee = uint64(10000000)
            mempool_item = MempoolItemInfo(
                cost,
                fee,
                uint32(i - 1),
            )
            items.append(mempool_item)

            fee1 = uint64(200000)
            mempool_item1 = MempoolItemInfo(
                cost,
                fee1,
                uint32(i - 40),
            )
            items.append(mempool_item1)

            fee2 = uint64(0)
            mempool_item2 = MempoolItemInfo(
                cost,
                fee2,
                uint32(i - 270),
            )
            items.append(mempool_item2)

        fee_tracker.process_block(uint32(i), items)

    short, med, long = fee_tracker.estimate_fees()

    assert short.median != -1
    assert med.median != -1
    assert long.median != -1


@pytest.mark.anyio
async def test_fee_increase() -> None:
    async with DBConnection(db_version=2) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        async with MempoolManager.managed(
            coin_store.get_coin_records,
            coin_store.get_unspent_lineage_info_for_puzzle_hash,
            test_constants,
            InlineExecutor(),
            validation_timeout=10,
            minimum_block_fee_per_cost=uint64(0),
        ) as mempool_manager:
            assert test_constants.MAX_BLOCK_COST_CLVM == mempool_manager.constants.MAX_BLOCK_COST_CLVM
            btc_fee_estimator: BitcoinFeeEstimator = mempool_manager.mempool.fee_estimator  # type: ignore[assignment]
            fee_tracker = btc_fee_estimator.get_tracker()
            estimator = SmartFeeEstimator(fee_tracker, uint64(test_constants.MAX_BLOCK_COST_CLVM))
            random = Random(x=1)
            for i in range(300, 700):
                items = []
                for _ in range(20):
                    fee = uint64(0)
                    included_height = uint32(random.randint(i - 60, i - 1))
                    cost = uint64(5000000)
                    mempool_item = MempoolItemInfo(
                        cost,
                        fee,
                        included_height,
                    )
                    items.append(mempool_item)

                fee_tracker.process_block(uint32(i), items)

            short, med, long = fee_tracker.estimate_fees()
            mempool_info = mempool_manager.mempool.fee_estimator.get_mempool_info()

            result = estimator.get_estimates(mempool_info, ignore_mempool=True)

            assert short.median == -1
            assert med.median == -1
            assert long.median == pytest.approx(0.0)

            assert result.error is None
            short_estimate = result.estimates[0].estimated_fee_rate
            med_estimate = result.estimates[1].estimated_fee_rate
            long_estimate = result.estimates[2].estimated_fee_rate

            assert short_estimate.mojos_per_clvm_cost == uint64(fee_tracker.buckets[3] / 1000)
            assert med_estimate.mojos_per_clvm_cost == uint64(fee_tracker.buckets[3] / 1000)
            assert long_estimate.mojos_per_clvm_cost == uint64(0)


def test_add_tx_counts_item_in_its_fee_rate_bucket() -> None:
    """
    Covers the scenario of a new mempool item to make sure it counts in the fee
    tracker as waiting once, in its proper fee rate bucket.
    """
    fee_tracker = FeeTracker(fee_store=FeeStore())
    # The tracker hasn't seen any block yet, so items enter at block 0, and
    # waiting ones are counted by the block they entered at.
    entry_block = 0
    mempool_item = MempoolItemInfo(cost=10_000_000, fee=50_000_000, height_added_to_mempool=uint32(entry_block))
    fee_tracker.add_tx(item=mempool_item)
    # Buckets are in mojos per `STORED_FEE_RATE_SCALE` cost. Each counts the fee
    # rates above its edge, up to the next bucket's.
    paid = mempool_item.fee_per_cost * STORED_FEE_RATE_SCALE
    for fee_stat in (fee_tracker.short_horizon, fee_tracker.med_horizon, fee_tracker.long_horizon):
        waiting = fee_stat.unconfirmed_txs[entry_block]
        [counted_in] = [bucket for bucket, count in enumerate(waiting) if count > 0]
        assert waiting[counted_in] == 1
        assert fee_stat.buckets[counted_in] < paid <= fee_stat.buckets[counted_in + 1]


def bucket_lowest_fee_rate(fee_tracker: FeeTracker, bucket_index: int) -> float:
    """
    The lowest fee rate (mojos per cost) that the tracker counts in the bucket.
    Buckets are in mojos per `STORED_FEE_RATE_SCALE` cost unit.
    """
    return fee_tracker.buckets[bucket_index] / STORED_FEE_RATE_SCALE


def horizon_fee_rate(fee_tracker: FeeTracker, fee_stat: FeeStat, target_blocks: int) -> float | None:
    """
    The fee rate (mojos per cost) the horizon estimates gets a transaction in
    within the target, or None when it has no answer.
    """
    estimate = fee_stat.estimate_median_val(
        conf_target=target_blocks,
        sufficient_tx_val=SUFFICIENT_FEE_TXS,
        success_break_point=SUCCESS_PCT,
        block_height=fee_tracker.latest_seen_height,
    )
    # It answers in mojos per `STORED_FEE_RATE_SCALE` cost, with a negative
    # median when it has no answer.
    if estimate.median < 0:
        return None
    return estimate.median / STORED_FEE_RATE_SCALE


def test_median_of_single_bucket_range() -> None:
    """
    Covers the scenario where the range of fee rate buckets that makes the next
    block is a single bucket, to make sure the median is searched in that bucket
    too, so the next block gets a proper estimate.
    """
    fee_tracker = FeeTracker(fee_store=FeeStore())
    # A cost this high turns these fee rates into whole mojo fees while keeping
    # the truncation error tiny.
    cost = 1_000_000_000
    high_bucket_index = 42
    low_bucket_index = high_bucket_index - 1
    # Here we pick 1% above each bucket's lower bound so that truncation keeps
    # them in it.
    above_lower_bound = 1.01
    high_rate = bucket_lowest_fee_rate(fee_tracker=fee_tracker, bucket_index=high_bucket_index) * above_lower_bound
    low_rate = bucket_lowest_fee_rate(fee_tracker=fee_tracker, bucket_index=low_bucket_index) * above_lower_bound
    items = [
        MempoolItemInfo(cost=cost, fee=int(cost * rate), height_added_to_mempool=uint32(0))
        for rate in (high_rate, low_rate)
    ]
    # Both get confirmed in the next block, so the low rate's bucket passes on
    # its own, as a range of a single bucket, which the median comes from.
    fee_tracker.process_block(block_height=uint32(1), items=items)
    next_block_fee_rate = horizon_fee_rate(fee_tracker=fee_tracker, fee_stat=fee_tracker.short_horizon, target_blocks=1)
    # Up to the fraction of a mojo the fee was cut down by
    assert next_block_fee_rate == pytest.approx(low_rate)
