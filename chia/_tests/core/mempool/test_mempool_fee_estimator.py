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
from chia.full_node.fee_tracker import FeeTracker
from chia.full_node.mempool_manager import MempoolManager


@pytest.mark.anyio
async def test_basics() -> None:
    fee_store = FeeStore()
    fee_tracker = FeeTracker(fee_store)

    cost = uint64(5000000)
    for i in range(300, 700):
        i = uint32(i)
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

        fee_tracker.process_block(i, items)

    short, med, long = fee_tracker.estimate_fees()

    assert short.median != -1
    assert med.median != -1
    assert long.median != -1


@pytest.mark.anyio
async def test_fee_increase() -> None:
    async with DBConnection(db_version=2) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        mempool_manager = MempoolManager(
            coin_store.get_coin_records, coin_store.get_unspent_lineage_info_for_puzzle_hash, test_constants
        )
        assert test_constants.MAX_BLOCK_COST_CLVM == mempool_manager.constants.MAX_BLOCK_COST_CLVM
        btc_fee_estimator: BitcoinFeeEstimator = mempool_manager.mempool.fee_estimator  # type: ignore
        fee_tracker = btc_fee_estimator.get_tracker()
        estimator = SmartFeeEstimator(fee_tracker, uint64(test_constants.MAX_BLOCK_COST_CLVM))
        random = Random(x=1)
        for i in range(300, 700):
            i = uint32(i)
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

            fee_tracker.process_block(i, items)

        short, med, long = fee_tracker.estimate_fees()
        mempool_info = mempool_manager.mempool.fee_estimator.get_mempool_info()

        result = estimator.get_estimates(mempool_info, ignore_mempool=True)

        assert short.median == -1
        assert med.median == -1
        assert long.median == 0.0

        assert result.error is None
        short_estimate = result.estimates[0].estimated_fee_rate
        med_estimate = result.estimates[1].estimated_fee_rate
        long_estimate = result.estimates[2].estimated_fee_rate

        assert short_estimate.mojos_per_clvm_cost == uint64(fee_tracker.buckets[3] / 1000)
        assert med_estimate.mojos_per_clvm_cost == uint64(fee_tracker.buckets[3] / 1000)
        assert long_estimate.mojos_per_clvm_cost == uint64(0)
