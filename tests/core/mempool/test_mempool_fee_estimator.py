import asyncio
import logging

import pytest

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.fee_tracker import FeeTracker
from chia.types.blockchain_format.coin import Coin
from chia.types.mempool_item import MempoolItem
from chia.util.wallet_tools import WalletTool
from tests.core.consensus.test_pot_iterations import test_constants


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFeeEstimator:
    @pytest.mark.asyncio
    async def test_basics(self):
        log = logging.getLogger(__name__)
        fee_estimator = FeeTracker(log)

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
