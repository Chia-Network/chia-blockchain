import logging
from typing import List, Dict

import pytest

from random import Random

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.coin_store import CoinStore
from chia.full_node.fee_estimate_store import FeeStore
from chia.full_node.fee_estimator import SmartFeeEstimator
from chia.full_node.fee_tracker import FeeTracker
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_item import MempoolItem
from tests.util.db_connection import DBConnection
from chia.util.ints import uint32, uint64
from tests.core.consensus.test_pot_iterations import test_constants

# TODO: Test the case where we cross the no-fee to mempool minimum fee threshold


@pytest.mark.asyncio
async def test_basics() -> None:
    log = logging.getLogger(__name__)

    fee_store = FeeStore()
    fee_tracker = FeeTracker(log, fee_store)

    wallet_tool = WalletTool(test_constants)
    ph = wallet_tool.get_new_puzzlehash()
    coin = Coin(ph, ph, uint64(10000))
    spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)
    cost = uint64(5000000)
    for i in range(300, 700):
        i = uint32(i)
        items = []
        for _ in range(2, 100):
            fee = uint64(10000000)
            mempool_item = MempoolItem(
                spend_bundle,
                fee,
                NPCResult(None, None, cost),
                cost,
                spend_bundle.name(),
                [],
                [],
                SerializedProgram(),
                uint32(i - 1),
            )
            items.append(mempool_item)

            fee1 = uint64(200000)
            mempool_item1 = MempoolItem(
                spend_bundle,
                fee1,
                NPCResult(None, None, cost),
                cost,
                spend_bundle.name(),
                [],
                [],
                SerializedProgram(),
                uint32(i - 40),
            )
            items.append(mempool_item1)

            fee2 = uint64(0)
            mempool_item2 = MempoolItem(
                spend_bundle,
                fee2,
                NPCResult(None, None, cost),
                cost,
                spend_bundle.name(),
                [],
                [],
                SerializedProgram(),
                uint32(i - 270),
            )
            items.append(mempool_item2)

        fee_tracker.process_block(i, items)

    short, med, long = fee_tracker.estimate_fees()

    assert short.median != -1
    assert med.median != -1
    assert long.median != -1


@pytest.mark.asyncio
async def test_fee_increase() -> None:
    # log = logging.getLogger(__name__)

    async with DBConnection(db_version=2) as db_wrapper:
        # fee_store = FeeStore()
        # fee_tracker = FeeTracker(log, fee_store)
        coin_store = await CoinStore.create(db_wrapper)
        mempool_manager = MempoolManager(coin_store, test_constants)
        assert test_constants.MAX_BLOCK_COST_CLVM == mempool_manager.constants.MAX_BLOCK_COST_CLVM
        estimator = SmartFeeEstimator(mempool_manager.mempool.fee_tracker, uint64(test_constants.MAX_BLOCK_COST_CLVM))
        wallet_tool = WalletTool(test_constants)
        ph = wallet_tool.get_new_puzzlehash()
        coin = Coin(ph, ph, uint64(10000))
        spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)
        random = Random(x=1)
        for i in range(300, 700):
            i = uint32(i)
            items = []
            for _ in range(0, 20):
                fee = uint64(0)
                included_height = uint32(random.randint(i - 60, i - 1))
                cost = uint64(5000000)
                mempool_item = MempoolItem(
                    spend_bundle,
                    fee,
                    NPCResult(None, None, cost),
                    cost,
                    spend_bundle.name(),
                    [],
                    [],
                    SerializedProgram(),
                    included_height,
                )
                items.append(mempool_item)

            mempool_manager.mempool.fee_tracker.process_block(i, items)

        short, med, long = mempool_manager.mempool.fee_tracker.estimate_fees()
        mempool_info = mempool_manager.get_mempool_info()

        result = estimator.get_estimates(mempool_info, ignore_mempool=True)

        assert short.median == -1
        assert med.median == -1
        assert long.median == 0.0

        assert result.error is None
        short_estimate = result.estimates[0].estimated_fee
        med_estimate = result.estimates[1].estimated_fee
        long_estimate = result.estimates[2].estimated_fee

        assert short_estimate == uint64(mempool_manager.mempool.fee_tracker.buckets[3] / 1000)
        assert med_estimate == uint64(mempool_manager.mempool.fee_tracker.buckets[3] / 1000)
        assert long_estimate == uint64(0)


@pytest.mark.asyncio
async def test_fee_increase_steps() -> None:
    # log = logging.getLogger(__name__)

    async with DBConnection(db_version=2) as db_wrapper:
        # fee_store = FeeStore()
        # fee_tracker = FeeTracker(log, fee_store)
        coin_store = await CoinStore.create(db_wrapper)
        mempool_manager = MempoolManager(coin_store, test_constants)
        estimator = SmartFeeEstimator(mempool_manager.mempool.fee_tracker, uint64(test_constants.MAX_BLOCK_COST_CLVM))
        wallet_tool = WalletTool(test_constants)
        ph = wallet_tool.get_new_puzzlehash()
        coin = Coin(ph, ph, uint64(10000))
        spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)
        random = Random(x=1)
        fee = uint64(0)
        for i in range(300, 1000):
            i = uint32(i)
            items = []
            for _ in range(0, 20):
                included_height = uint32(random.randint(1, i - 1))
                cost = uint64(5000000)
                mempool_item = MempoolItem(
                    spend_bundle,
                    fee,
                    NPCResult(None, None, cost),
                    cost,
                    spend_bundle.name(),
                    [],
                    [],
                    SerializedProgram(),
                    included_height,
                )
                items.append(mempool_item)

            mempool_manager.mempool.fee_tracker.process_block(i, items)
            mempool_info = mempool_manager.get_mempool_info()
            result = estimator.get_estimates(mempool_info, ignore_mempool=True)

            # XXX
            if result.error is not None or len(result.estimates) < 1 or result.estimates[0].error is not None:
                fee = uint64(0)
            else:
                short_estimate = result.estimates[0].estimated_fee
                fee = uint64(short_estimate * 5000000)

        # With fee updating and included height being random, fee should increase to the max
        assert fee == uint64(mempool_manager.mempool.fee_tracker.buckets[-1] * 5000)


@pytest.mark.asyncio
async def test_fee_with_throughput(latest_db_version: int) -> None:
    # log = logging.getLogger(__name__)

    async with DBConnection(latest_db_version) as db_wrapper:

        # fee_store = FeeStore()
        # fee_tracker = FeeTracker(log, fee_store)
        coin_store = await CoinStore.create(db_wrapper)
        mempool_manager = MempoolManager(coin_store, test_constants)
        estimator = SmartFeeEstimator(mempool_manager.mempool.fee_tracker, uint64(test_constants.MAX_BLOCK_COST_CLVM))
        wallet_tool = WalletTool(test_constants)
        ph = wallet_tool.get_new_puzzlehash()
        coin = Coin(ph, ph, uint64(10000))
        spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)
        random = Random(x=1)

        for i in range(300, 1000):
            i = uint32(i)
            items = []
            for _ in range(0, 20):
                mempool_info = mempool_manager.get_mempool_info()
                estimates = estimator.get_estimates(mempool_info, ignore_mempool=True)

                if estimates.error is not None:
                    fee = uint64(0)
                    included_height = random.randint(1, i - 1)
                else:
                    # Select a valid fee estimate
                    e = []
                    period = [3, 30, 60]
                    for j in range(0, len(estimates.estimates)):
                        if estimates.estimates[j].error is None:
                            fee_estimate = estimates.estimates[j].estimated_fee
                            height = uint32(random.randint(i - period[j], i - 1))
                            e.append((uint64(fee_estimate * 5000000), height))

                    # assert len(e) > 0  # Because estimates.error is not None
                    if len(e) > 0:
                        breakpoint()
                        choice = random.randint(0, len(e))
                        fee, included_height = e[choice]
                    else:
                        fee = uint64(0)
                        included_height = random.randint(1, i - 1)

                mempool_item = MempoolItem(
                    spend_bundle,
                    fee,
                    NPCResult(None, None, uint64(5000000)),
                    uint64(5000000),
                    spend_bundle.name(),
                    [],
                    [],
                    SerializedProgram(),
                    uint32(included_height),
                )
                items.append(mempool_item)

            mempool_manager.mempool.fee_tracker.process_block(i, items)

        mempool_info = mempool_manager.get_mempool_info()
        estimates = estimator.get_estimates(mempool_info, ignore_mempool=True)
        short = estimates.estimates[0].estimated_fee
        medium = estimates.estimates[1].estimated_fee
        long = estimates.estimates[2].estimated_fee
        assert float(short) > float(medium)
        assert float(medium) > float(long)

        # Validate that estimate store works
        mempool_manager.mempool.fee_tracker.shutdown()
        await db_wrapper.close()

        # new_fee_store = FeeStore()
        # new_fee_tracker = FeeTracker(log, new_fee_store)
        new_mempool_manager = MempoolManager(coin_store, test_constants)

        new_estimator = SmartFeeEstimator(
            mempool_manager.mempool.fee_tracker, uint64(test_constants.MAX_BLOCK_COST_CLVM)
        )
        mempool_info = new_mempool_manager.get_mempool_info()
        new_estimates = new_estimator.get_estimates(mempool_info, ignore_mempool=True)
        assert estimates == new_estimates


def make_tx(
    wallet_tool: WalletTool, blocknum: uint32, i: int, j: int, ph: bytes32, coin: Coin, fee: uint64
) -> MempoolItem:
    spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000 + i + j * 10 + blocknum * 100), ph, coin)
    return MempoolItem(
        spend_bundle,
        fee,
        NPCResult(None, None, uint64(5000000)),
        uint64(5000000),  # clvm cost
        spend_bundle.name(),
        [],
        [],
        SerializedProgram(),
        blocknum,
    )


def remove_from_mempool(
    mpool: Dict[bytes32, MempoolItem], block_items: List[MempoolItem]
) -> Dict[bytes32, MempoolItem]:
    # assert len(block_items) > 0
    for item in block_items:
        try:
            mpool.pop(item.spend_bundle.get_hash())
        except KeyError:
            breakpoint()
    return mpool


async def calc_baserate(wallet_tool: WalletTool, mempool_manager: MempoolManager, basefee: uint64) -> float:
    ph = wallet_tool.get_new_puzzlehash()
    coin = Coin(ph, ph, uint64(10000))
    eg_spend_bundle = wallet_tool.generate_signed_transaction(uint64(10000), ph, coin)
    npc = await mempool_manager.pre_validate_spendbundle(eg_spend_bundle, None, eg_spend_bundle.name())
    return basefee / npc.cost


def verify(mpool: Dict[bytes32, MempoolItem], tx_hashes: List[List[bytes32]]) -> None:
    count = 0
    for bucket in tx_hashes:
        for tx_id in bucket:
            count += 1
            assert tx_id in mpool
    if len(mpool) != count:
        breakpoint()
    # assert len(mpool) == count


@pytest.mark.asyncio
async def test_fee_estimation_long(latest_db_version: int) -> None:
    # https://github.com/bitcoin/bitcoin/blob/master/src/test/policyestimator_tests.cpp

    async with DBConnection(latest_db_version) as db_wrapper:

        # fee_store = FeeStore()
        # fee_tracker = FeeTracker(log, fee_store)
        coin_store = await CoinStore.create(db_wrapper)
        mempool_manager = MempoolManager(coin_store, test_constants)
        # estimator = SmartFeeEstimator(mempool_manager.mempool.fee_tracker, uint64(test_constants.MAX_BLOCK_COST_CLVM))
        wallet_tool = WalletTool(test_constants)
        fee_est = mempool_manager.mempool.fee_estimator
        # random = Random(x=1)
        basefee = uint64(2000000)
        deltaFee = 100000

        baserate = await calc_baserate(wallet_tool, mempool_manager, basefee)
        ph = wallet_tool.get_new_puzzlehash()
        coin = Coin(ph, ph, uint64(10000))

        feeV = [uint64(basefee * n) for n in range(1, 11)]  # test_fees
        assert len(feeV) == 10

        # Loop through 200 blocks with a decay of 0.9952 and 4 fee transactions per block
        # This makes the tx count about 2.5 per bucket, well above the 0.1 threshold
        mpool = {}
        blocknum: uint32 = uint32(0)
        for blocknum in [uint32(block) for block in range(0, 200)]:
            block_items = []
            # Store the hashes of transactions that have been added to the mempool by their associated fee in tx_hashes
            tx_hashes: List[List[bytes32]] = [[] for _ in range(10)]
            for j, fee in enumerate(feeV):
                for k in range(4):
                    spend_bundle = wallet_tool.generate_signed_transaction(
                        uint64(10000 * blocknum + 100 * j + k), ph, coin
                    )
                    item = MempoolItem(
                        spend_bundle,
                        fee,
                        NPCResult(None, None, uint64(5000000)),
                        uint64(5000000),  # clvm cost
                        spend_bundle.name(),
                        [],
                        [],
                        SerializedProgram(),
                        blocknum,
                    )
                    # mempool_manager.mempool.add_to_pool(item)
                    # block_items.append(item)
                    tx_hashes[j].append(item.spend_bundle.name())
                    mpool[item.spend_bundle.name()] = item
                    # verify(mpool, tx_hashes)

            # Create blocks where higher fee txs are included more often
            for h in range((blocknum % 10) + 1):
                # 10/10 blocks add the highest fee transactions
                # 9/10 blocks add 2nd highest and so on until ...
                # 1/10 blocks add lowest fee transactions
                while len(tx_hashes[9 - h]):
                    name = tx_hashes[9 - h].pop(-1)
                    item = mpool[name]
                    block_items.append(item)
                    # tx_hashes[j].append(item.spend_bundle.name())
                    # mpool[item.spend_bundle.name()] = item

            mpool = remove_from_mempool(mpool, block_items)
            mempool_manager.mempool.fee_tracker.process_block(blocknum, block_items)
            # mpool.removeForBlock(block, ++blocknum)
            # block.clear()
            # Check after just a few txs that combining buckets works as expected
            if blocknum == 100:  # xxx 3
                # At this point we should need to combine 3 buckets to get enough data points
                # So estimate_fee_for_block(1) should fail and estimate_fee_for_block(2) should return somewhere around
                # 9*baserate.  estimate_fee_for_block(2) %'s are 100,100,90 = average 97%
                # b1_estimate = fee_est.estimate_fee_for_block(uint32(1))
                block_1_estimate = fee_est.estimate_fee_for_block(uint32(1))
                block_2_estimate = fee_est.estimate_fee_for_block(uint32(2))
                assert block_1_estimate == 0
                assert block_2_estimate < 9 * baserate * 1000 + deltaFee
                assert block_2_estimate > 9 * baserate * 1000 - deltaFee

        # Highest feerate is 10*baserate and gets in all blocks,
        # second highest feerate is 9*baserate and gets in 9/10 blocks = 90%,
        # third highest feerate is 8*base rate, and gets in 8/10 blocks = 80%,
        # so estimate_fee_for_block(1) would return 10*baserate but is hardcoded to return failure
        # Second highest feerate has 100% chance of being included by 2 blocks,
        # so estimate_fee_for_block(2) should return 9*baserate etc...
        orig_fee_est: List[uint64] = []
        for k in range(1, 10):
            orig_fee_est.append(fee_est.estimate_fee_for_block(uint32(k)))  # xxx .GetFeePerK()
            if k > 2:
                # Fee estimates should be monotonically decreasing
                assert orig_fee_est[k - 1] <= orig_fee_est[k - 2]
            mult = 11 - k
            if k % 2 == 0:
                # At scale 2, test logic is only correct for even targets
                # xxx GetFeePerK()
                # assert orig_fee_est[k - 1] < mult * baserate.GetFeePerK() + deltaFee
                # assert orig_fee_est[k - 1] > mult * baserate.GetFeePerK() - deltaFee
                assert orig_fee_est[k - 1] < uint64(mult * baserate + deltaFee)
                assert orig_fee_est[k - 1] > uint64(mult * baserate - deltaFee)
        # Fill out rest of the original estimates
        for k in range(10, 49):
            # orig_fee_est.append(fee_est.estimate_fee_for_block(uint32(k)).GetFeePerK())
            orig_fee_est.append(fee_est.estimate_fee_for_block(uint32(k)))

        # Farm 50 more blocks with no transactions happening; estimates shouldn't change.
        # We haven't decayed the moving average enough - we still have enough data points in every bucket
        while blocknum < 250:
            blocknum = uint32(blocknum + 1)
            mempool_manager.mempool.fee_tracker.process_block(uint32(blocknum), [])

        assert fee_est.estimate_fee_for_block(uint32(1)) == uint64(0)
        for k in range(2, 10):
            # assert fee_est.estimate_fee_for_block(uint32(k)).GetFeePerK() < orig_fee_est[k - 1] + deltaFee
            # assert fee_est.estimate_fee_for_block(uint32(k)).GetFeePerK() > orig_fee_est[k - 1] - deltaFee
            assert fee_est.estimate_fee_for_block(uint32(k)) < orig_fee_est[k - 1] + deltaFee
            assert fee_est.estimate_fee_for_block(uint32(k)) > orig_fee_est[k - 1] - deltaFee

        # farm 15 more blocks with lots of transactions entering the mempool and not getting farmed
        # Estimates should go up
        while blocknum < 265:
            block_items = []
            tx_hashes = [[] for _ in range(10)]
            for j in range(0, 10):  # For each fee multiple
                for k in range(0, 4):  # add 4 fee txs
                    item = make_tx(wallet_tool, uint32(blocknum), j, k, ph, coin, fee)
                    block_items.append(item)
                    mpool[item.spend_bundle.name()] = item
                    tx_hashes[j].append(item.spend_bundle.name())

                    # tx.vin[0].prevout.n = 10000 * blocknum + 100 * j + k
                    # hash: uint256 = tx.GetHash()
                    # mpool.addUnchecked(entry.Fee(feeV[j]).Time(GetTime()).Height(blocknum).FromTx(tx))
                    # tx_hashes[j].push_back(hash)
            blocknum = uint32(blocknum + 1)
            # mpool.removeForBlock(block, blocknum)
            mpool = remove_from_mempool(mpool, block_items)
            mempool_manager.mempool.fee_tracker.process_block(blocknum, block_items)

        for k in range(1, 10):
            assert (
                fee_est.estimate_fee_for_block(uint32(k)) == uint64(0)  # xxx check CRate definition CFeeRate(0)
                or fee_est.estimate_fee_for_block(uint32(k)) > orig_fee_est[k - 1] - deltaFee
                # or fee_est.estimate_fee_for_block(uint32(k)).GetFeePerK() > orig_fee_est[k - 1] - deltaFee
            )

        # farm all those transactions
        # Estimates should still not be below original
        block_items = []
        tx_hashes = [[] for _ in range(10)]
        for j in range(0, 10):
            while len(tx_hashes[j]) > 0:
                tx = mpool.get(tx_hashes[j][-1])
                assert tx is not None
                block_items.append(tx)
                tx_hashes[j].remove(tx_hashes[j][-1])

        mpool = remove_from_mempool(mpool, block_items)
        mempool_manager.mempool.fee_tracker.process_block(blocknum, block_items)
        # assert fee_est.estimate_fee_for_block(1) == uint64(0)
        for k in range(2, 10):
            assert (
                fee_est.estimate_fee_for_block(uint32(k)) == uint64(0)
                or fee_est.estimate_fee_for_block(uint32(k)) > orig_fee_est[k - 1] - deltaFee
                # or fee_est.estimate_fee_for_block(uint32(k)).GetFeePerK() > orig_fee_est[k - 1] - deltaFee
            )

        # farm 400 more blocks where all incoming SpendBundles are farmed every block
        # Estimates should be below original estimates
        while blocknum < 665:
            tx_hashes = [[] for _ in range(10)]
            block_items = []
            for j in range(0, 10):  # For each fee multiple
                for k in range(0, 4):  # add 4 fee txs
                    # tx.vin[0].prevout.n = 10000 * blocknum + 100 * j + k
                    # hash: uint256 = tx.GetHash()
                    # mpool.addUnchecked(entry.Fee(feeV[j]).Time(GetTime()).Height(blocknum).FromTx(tx))
                    # ptx: CTransactionRef = mpool.get(hash)
                    # if ptx is not None:
                    #    block_items.(ptx)

                    item = make_tx(wallet_tool, blocknum, j, k, ph, coin, fee)
                    block_items.append(item)
                    mpool[item.spend_bundle.name()] = item
                    tx_hashes[j].append(item.spend_bundle.name())
            blocknum = uint32(blocknum + 1)
            mpool = remove_from_mempool(mpool, block_items)
            mempool_manager.mempool.fee_tracker.process_block(blocknum, block_items)

        assert fee_est.estimate_fee_for_block(uint32(1)) == uint64(0)
        for k in range(2, 9):  # At 9, the original estimate was already at the bottom (b/c scale = 2)
            assert fee_est.estimate_fee_for_block(uint32(k)) < orig_fee_est[k - 1] - deltaFee
            # assert fee_est.estimate_fee_for_block(uint32(k)).GetFeePerK() < orig_fee_est[k - 1] - deltaFee
