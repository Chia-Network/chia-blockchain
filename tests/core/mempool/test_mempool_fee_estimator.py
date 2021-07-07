import asyncio
import logging
from pathlib import Path
from random import Random
import aiosqlite
import pytest
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.coin_store import CoinStore
from chia.full_node.fee_estimate_store import FeeStore
from chia.full_node.fee_estimator import SmartFeeEstimator
from chia.full_node.fee_tracker import FeeTracker
from chia.full_node.mempool_manager import MempoolManager
from chia.types.blockchain_format.coin import Coin
from chia.types.mempool_item import MempoolItem
from chia.util.db_wrapper import DBWrapper
from tests.core.consensus.test_pot_iterations import test_constants
from tests.setup_nodes import bt
from tests.wallet_tools import WalletTool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFeeEstimator:
    @pytest.mark.asyncio
    async def test_basics(self):
        log = logging.getLogger(__name__)
        path = Path("./fee_test_db")
        db_connection = await aiosqlite.connect(path)
        try:
            db_wrapper = DBWrapper(db_connection)
            fee_store = await FeeStore.create(db_wrapper)
            fee_estimator = await FeeTracker.create(log, fee_store)

            wallet_tool = WalletTool(test_constants)
            ph = wallet_tool.get_new_puzzlehash()
            coin = Coin(ph, ph, 10000)
            spend_bundle = wallet_tool.generate_signed_transaction(10000, ph, coin)
            for i in range(300, 700):
                items = []
                for _ in range(2, 100):
                    fee = 10000000
                    mempool_item = MempoolItem(
                        spend_bundle, fee, NPCResult(None, [], 0), 5000000, spend_bundle.name(), [], [], 0, i - 1
                    )
                    items.append(mempool_item)

                    fee1 = 200000
                    mempool_item1 = MempoolItem(
                        spend_bundle, fee1, NPCResult(None, [], 0), 5000000, spend_bundle.name(), [], [], 0, i - 40
                    )
                    items.append(mempool_item1)

                    fee2 = 0
                    mempool_item2 = MempoolItem(
                        spend_bundle, fee2, NPCResult(None, [], 0), 5000000, spend_bundle.name(), [], [], 0, i - 270
                    )
                    items.append(mempool_item2)

                fee_estimator.process_block(i, items)

            short, med, long = fee_estimator.estimate_fee()
            short_median = short[2]
            med_median = med[2]
            long_median = long[2]
            assert short_median != -1
            assert med_median != -1
            assert long_median != -1
        except BaseException:
            raise
        finally:
            await db_connection.close()
            path.unlink()

    @pytest.mark.asyncio
    async def test_fee_increase(self):
        log = logging.getLogger(__name__)
        path = Path("./fee_test_db")
        db_connection = await aiosqlite.connect(path)
        try:
            db_wrapper = DBWrapper(db_connection)
            fee_store = await FeeStore.create(db_wrapper)
            fee_tracker = await FeeTracker.create(log, fee_store)
            coin_store = await CoinStore.create(fee_store)
            mpool = MempoolManager(coin_store, test_constants, bt.config, fee_tracker)
            estimator = SmartFeeEstimator(mpool, log)
            wallet_tool = WalletTool(test_constants)
            ph = wallet_tool.get_new_puzzlehash()
            coin = Coin(ph, ph, 10000)
            spend_bundle = wallet_tool.generate_signed_transaction(10000, ph, coin)
            random = Random(x=1)
            for i in range(300, 700):
                items = []
                for _ in range(0, 20):
                    fee = 0
                    included_height = random.randint(1, i - 1)

                    mempool_item = MempoolItem(
                        spend_bundle,
                        fee,
                        NPCResult(None, [], 0),
                        5000000,
                        spend_bundle.name(),
                        [],
                        [],
                        0,
                        included_height,
                    )
                    items.append(mempool_item)

                fee_tracker.process_block(i, items)

            short, med, long = fee_tracker.estimate_fee()
            short_median = short[2]
            med_median = med[2]
            long_median = long[2]
            estimates = estimator.get_estimates(ignore_mempool=True)

            assert short_median == -1
            assert med_median == -1
            assert long_median == 0.0

            assert estimates.error is None
            assert float(estimates.short) == fee_tracker.buckets[3] / 1000
            assert float(estimates.medium) == fee_tracker.buckets[3] / 1000
            assert float(estimates.long) == 0.0

        except BaseException:
            raise
        finally:
            await db_connection.close()
            path.unlink()

    @pytest.mark.asyncio
    async def test_fee_increase_steps(self):
        log = logging.getLogger(__name__)
        path = Path("./fee_test_db")
        db_connection = await aiosqlite.connect(path)
        try:
            db_wrapper = DBWrapper(db_connection)
            fee_store = await FeeStore.create(db_wrapper)
            fee_tracker = await FeeTracker.create(log, fee_store)
            coin_store = await CoinStore.create(fee_store)
            mpool = MempoolManager(coin_store, test_constants, bt.config, fee_tracker)
            estimator = SmartFeeEstimator(mpool, log)
            wallet_tool = WalletTool(test_constants)
            ph = wallet_tool.get_new_puzzlehash()
            coin = Coin(ph, ph, 10000)
            spend_bundle = wallet_tool.generate_signed_transaction(10000, ph, coin)
            random = Random(x=1)
            fee = 0
            for i in range(300, 1000):
                items = []
                for _ in range(0, 20):
                    included_height = random.randint(1, i - 1)

                    mempool_item = MempoolItem(
                        spend_bundle,
                        fee,
                        NPCResult(None, [], 0),
                        5000000,
                        spend_bundle.name(),
                        [],
                        [],
                        0,
                        included_height,
                    )
                    items.append(mempool_item)

                fee_tracker.process_block(i, items)
                estimates = estimator.get_estimates(ignore_mempool=True)

                if float(estimates.short) == -1:
                    fee = 0
                else:
                    fee = float(estimates.short) * 5000000

            # With fee updating and included height being random, fee should increase to the max
            assert fee == fee_tracker.buckets[-1] * 5000
        except BaseException:
            raise
        finally:
            await db_connection.close()
            path.unlink()

    @pytest.mark.asyncio
    async def test_fee_with_throughput(self):
        log = logging.getLogger(__name__)
        path = Path("./fee_test_db")
        db_connection = await aiosqlite.connect(path)
        try:
            db_wrapper = DBWrapper(db_connection)
            fee_store = await FeeStore.create(db_wrapper)
            fee_tracker = await FeeTracker.create(log, fee_store)
            coin_store = await CoinStore.create(fee_store)
            mpool = MempoolManager(coin_store, test_constants, bt.config, fee_tracker)
            estimator = SmartFeeEstimator(mpool, log)
            wallet_tool = WalletTool(test_constants)
            ph = wallet_tool.get_new_puzzlehash()
            coin = Coin(ph, ph, 10000)
            spend_bundle = wallet_tool.generate_signed_transaction(10000, ph, coin)
            random = Random(x=1)
            fee = 0
            for i in range(300, 1000):
                items = []
                for _ in range(0, 20):
                    estimates = estimator.get_estimates(ignore_mempool=True)
                    if float(estimates.short) == -1:
                        fee = 0
                        included_height = random.randint(1, i - 1)
                    else:
                        random_fee = random.randint(0, 3)
                        if random_fee == 0:
                            fee = float(estimates.short) * 5000000
                            included_height = random.randint(i - 10, i - 1)
                        elif random_fee == 1:
                            fee = float(estimates.medium) * 5000000
                            included_height = random.randint(i - 60, i - 1)
                        else:
                            fee = float(estimates.long) * 5000000
                            included_height = random.randint(i - 300, i - 1)

                    mempool_item = MempoolItem(
                        spend_bundle,
                        fee,
                        NPCResult(None, [], 0),
                        5000000,
                        spend_bundle.name(),
                        [],
                        [],
                        0,
                        included_height,
                    )
                    items.append(mempool_item)

                fee_tracker.process_block(i, items)

            estimates = estimator.get_estimates(ignore_mempool=True)
            assert float(estimates.short) > float(estimates.medium)
            assert float(estimates.medium) > float(estimates.long)
        except BaseException:
            raise
        finally:
            await db_connection.close()
            path.unlink()
