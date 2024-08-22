from __future__ import annotations

import dataclasses
import logging
import random
from typing import Callable, Dict, List, Optional, Tuple

import pytest
from chia_rs import G1Element, G2Element
from clvm.casts import int_to_bytes
from clvm_tools import binutils

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.connection_utils import add_dummy_connection, connect_and_get_peer
from chia._tests.core.mempool.test_mempool_manager import (
    IDENTITY_PUZZLE_HASH,
    TEST_COIN,
    assert_sb_in_pool,
    assert_sb_not_in_pool,
    make_test_coins,
    mempool_item_from_spendbundle,
    mk_item,
    spend_bundle_from_conditions,
)
from chia._tests.core.node_height import node_height_at_least
from chia._tests.util.misc import BenchmarkRunner, invariant_check_mempool
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.condition_costs import ConditionCost
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.fee_estimation import EmptyMempoolInfo, MempoolInfo
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.mempool import Mempool
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, get_puzzle_and_solution_for_coin
from chia.full_node.mempool_manager import MEMPOOL_MIN_FEE_INCREASE
from chia.full_node.pending_tx_cache import ConflictTxCache, PendingTxCache
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.wallet_protocol import TransactionAck
from chia.server.outbound_message import Message
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools, test_constants
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.clvm_cost import CLVMCost
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.eligible_coin_spends import UnspentLineageInfo, run_for_cost
from chia.types.fee_rate import FeeRate
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle, estimate_fees
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.api_decorators import api_request
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.util.recursive_replace import recursive_replace
from chia.wallet.conditions import AssertCoinAnnouncement, AssertPuzzleAnnouncement

BURN_PUZZLE_HASH = bytes32(b"0" * 32)
BURN_PUZZLE_HASH_2 = bytes32(b"1" * 32)

log = logging.getLogger(__name__)


def new_mi(mi: MempoolInfo, max_mempool_cost: int, min_replace_fee_per_cost: int) -> MempoolInfo:
    return dataclasses.replace(
        mi,
        minimum_fee_per_cost_to_replace=FeeRate(uint64(min_replace_fee_per_cost)),
        max_size_in_cost=CLVMCost(uint64(max_mempool_cost)),
    )


@pytest.fixture(scope="module")
def wallet_a(bt: BlockTools) -> WalletTool:
    return bt.get_pool_wallet_tool()


def generate_test_spend_bundle(
    wallet: WalletTool,
    coin: Coin,
    condition_dic: Optional[Dict[ConditionOpcode, List[ConditionWithArgs]]] = None,
    fee: uint64 = uint64(0),
    amount: uint64 = uint64(1000),
    new_puzzle_hash: bytes32 = BURN_PUZZLE_HASH,
) -> SpendBundle:
    if condition_dic is None:
        condition_dic = {}
    transaction = wallet.generate_signed_transaction(amount, new_puzzle_hash, coin, condition_dic, fee)
    assert transaction is not None
    return transaction


def make_item(
    idx: int, cost: uint64 = uint64(80), assert_height: uint32 = uint32(100), fee: uint64 = uint64(0)
) -> MempoolItem:
    spend_bundle_name = bytes32([idx] * 32)
    return MempoolItem(
        SpendBundle([], G2Element()),
        fee,
        SpendBundleConditions([], 0, 0, 0, None, None, [], cost, 0, 0),
        spend_bundle_name,
        uint32(0),
        assert_height,
    )


class TestConflictTxCache:
    def test_recall(self) -> None:
        c = ConflictTxCache(100)
        item = make_item(1)
        c.add(item)
        assert c.get(item.name) == item
        tx = c.drain()
        assert tx == {item.spend_bundle_name: item}

    def test_fifo_limit(self) -> None:
        c = ConflictTxCache(200)
        # each item has cost 80
        items = [make_item(i) for i in range(1, 4)]
        for i in items:
            c.add(i)
        # the max cost is 200, only two transactions will fit
        # we evict items FIFO, so the to most recently added will be left
        tx = c.drain()
        assert tx == {items[-2].spend_bundle_name: items[-2], items[-1].spend_bundle_name: items[-1]}

    def test_item_limit(self) -> None:
        c = ConflictTxCache(1000000, 2)
        # each item has cost 80
        items = [make_item(i) for i in range(1, 4)]
        for i in items:
            c.add(i)
        # the max size is 2, only two transactions will fit
        # we evict items FIFO, so the to most recently added will be left
        tx = c.drain()
        assert tx == {items[-2].spend_bundle_name: items[-2], items[-1].spend_bundle_name: items[-1]}

    def test_drain(self) -> None:
        c = ConflictTxCache(100)
        item = make_item(1)
        c.add(item)
        tx = c.drain()
        assert tx == {item.spend_bundle_name: item}

        # drain will clear the cache, so a second call will be empty
        tx = c.drain()
        assert tx == {}

    def test_cost(self) -> None:
        c = ConflictTxCache(200)
        assert c.cost() == 0
        item1 = make_item(1)
        c.add(item1)
        # each item has cost 80
        assert c.cost() == 80

        item2 = make_item(2)
        c.add(item2)
        assert c.cost() == 160

        # the first item is evicted, so the cost stays the same
        item3 = make_item(3)
        c.add(item3)
        assert c.cost() == 160

        tx = c.drain()
        assert tx == {item2.spend_bundle_name: item2, item3.spend_bundle_name: item3}

        assert c.cost() == 0
        item4 = make_item(4)
        c.add(item4)
        assert c.cost() == 80

        tx = c.drain()
        assert tx == {item4.spend_bundle_name: item4}


class TestPendingTxCache:
    def test_recall(self) -> None:
        c = PendingTxCache(100)
        item = make_item(1)
        c.add(item)
        assert c.get(item.name) == item
        tx = c.drain(uint32(101))
        assert tx == {item.spend_bundle_name: item}

    def test_fifo_limit(self) -> None:
        c = PendingTxCache(200)
        # each item has cost 80
        items = [make_item(i) for i in range(1, 4)]
        for i in items:
            c.add(i)
        # the max cost is 200, only two transactions will fit
        # the eviction is FIFO because all items have the same assert_height
        tx = c.drain(uint32(101))
        assert tx == {items[-2].spend_bundle_name: items[-2], items[-1].spend_bundle_name: items[-1]}

    def test_add_eviction(self) -> None:
        c = PendingTxCache(160)
        item = make_item(1)
        c.add(item)

        for i in range(3):
            item = make_item(i + 1, assert_height=uint32(50))
            c.add(item)

        txs = c.drain(uint32(161))
        assert len(txs) == 2
        for tx in txs.values():
            assert tx.assert_height == 50

    def test_item_limit(self) -> None:
        c = PendingTxCache(1000000, 2)
        # each item has cost 80
        items = [make_item(i) for i in range(1, 4)]
        for i in items:
            c.add(i)
        # the max size is 2, only two transactions will fit
        # the eviction is FIFO because all items have the same assert_height
        tx = c.drain(uint32(101))
        assert tx == {items[-2].spend_bundle_name: items[-2], items[-1].spend_bundle_name: items[-1]}

    def test_drain(self) -> None:
        c = PendingTxCache(100)
        item = make_item(1)
        c.add(item)
        tx = c.drain(uint32(101))
        assert tx == {item.spend_bundle_name: item}

        # drain will clear the cache, so a second call will be empty
        tx = c.drain(uint32(101))
        assert tx == {}

    def test_cost(self) -> None:
        c = PendingTxCache(200)
        assert c.cost() == 0
        item1 = make_item(1)
        c.add(item1)
        # each item has cost 80
        assert c.cost() == 80

        item2 = make_item(2)
        c.add(item2)
        assert c.cost() == 160

        # the first item is evicted, so the cost stays the same
        item3 = make_item(3)
        c.add(item3)
        assert c.cost() == 160

        tx = c.drain(uint32(101))
        assert tx == {item2.spend_bundle_name: item2, item3.spend_bundle_name: item3}

        assert c.cost() == 0
        item4 = make_item(4)
        c.add(item4)
        assert c.cost() == 80

        tx = c.drain(uint32(101))
        assert tx == {item4.spend_bundle_name: item4}

    def test_drain_height(self) -> None:
        c = PendingTxCache(20000, 1000)

        # each item has cost 80
        # heights are 100-109
        items = [make_item(i, assert_height=uint32(100 + i)) for i in range(10)]
        for i in items:
            c.add(i)

        tx = c.drain(uint32(101))
        assert tx == {items[0].spend_bundle_name: items[0]}

        tx = c.drain(uint32(105))
        assert tx == {
            items[1].spend_bundle_name: items[1],
            items[2].spend_bundle_name: items[2],
            items[3].spend_bundle_name: items[3],
            items[4].spend_bundle_name: items[4],
        }

        tx = c.drain(uint32(105))
        assert tx == {}

        tx = c.drain(uint32(110))
        assert tx == {
            items[5].spend_bundle_name: items[5],
            items[6].spend_bundle_name: items[6],
            items[7].spend_bundle_name: items[7],
            items[8].spend_bundle_name: items[8],
            items[9].spend_bundle_name: items[9],
        }


class TestMempool:
    @pytest.mark.anyio
    async def test_basic_mempool(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)

        max_block_cost_clvm = uint64(40000000)
        max_mempool_cost = max_block_cost_clvm * 5
        mempool_info = new_mi(EmptyMempoolInfo, max_mempool_cost, uint64(5))
        fee_estimator = create_bitcoin_fee_estimator(max_block_cost_clvm)
        mempool = Mempool(mempool_info, fee_estimator)
        assert mempool.get_min_fee_rate(104000) == 0

        assert mempool.get_min_fee_rate(max_mempool_cost + 1) is None

        coin = await next_block(full_node_1, wallet_a, bt)
        spend_bundle = generate_test_spend_bundle(wallet_a, coin)
        assert spend_bundle is not None


@api_request(peer_required=True, bytes_required=True)
async def respond_transaction(
    self: FullNodeAPI,
    tx: full_node_protocol.RespondTransaction,
    peer: WSChiaConnection,
    tx_bytes: bytes = b"",
    test: bool = False,
) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
    """
    Receives a full transaction from peer.
    If tx is added to mempool, send tx_id to others. (new_transaction)
    """
    assert tx_bytes != b""
    spend_name = std_hash(tx_bytes)
    if spend_name in self.full_node.full_node_store.pending_tx_request:
        self.full_node.full_node_store.pending_tx_request.pop(spend_name)
    if spend_name in self.full_node.full_node_store.peers_with_tx:
        self.full_node.full_node_store.peers_with_tx.pop(spend_name)
    ret = await self.full_node.add_transaction(tx.transaction, spend_name, peer, test)
    invariant_check_mempool(self.full_node.mempool_manager.mempool)
    return ret


async def next_block(full_node_1: FullNodeSimulator, wallet_a: WalletTool, bt: BlockTools) -> Coin:
    blocks = await full_node_1.get_all_full_blocks()
    # we have to farm a new block here, to ensure every test has a unique coin to test spending.
    # all this could be simplified if the tests did not share a simulation
    start_height = blocks[-1].height
    reward_ph = wallet_a.get_new_puzzlehash()
    blocks = bt.get_consecutive_blocks(
        1,
        block_list_input=blocks,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
        genesis_timestamp=uint64(10_000),
        time_per_block=10,
    )

    for block in blocks:
        await full_node_1.full_node.add_block(block)

    await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 1)
    return blocks[-1].get_included_reward_coins()[0]


co = ConditionOpcode
mis = MempoolInclusionStatus


async def send_sb(node: FullNodeAPI, sb: SpendBundle) -> Optional[Message]:
    tx = wallet_protocol.SendTransaction(sb)
    return await node.send_transaction(tx, test=True)


async def gen_and_send_sb(node: FullNodeAPI, wallet: WalletTool, coin: Coin, fee: uint64 = uint64(0)) -> SpendBundle:
    sb = generate_test_spend_bundle(wallet=wallet, coin=coin, fee=fee)
    assert sb is not None
    await send_sb(node, sb)
    return sb


class TestMempoolManager:
    @pytest.mark.anyio
    async def test_basic_mempool_manager(
        self,
        two_nodes_one_block: Tuple[FullNodeSimulator, FullNodeSimulator, ChiaServer, ChiaServer, BlockTools],
        wallet_a: WalletTool,
        self_hostname: str,
    ) -> None:
        full_node_1, full_node_2, server_1, server_2, bt = two_nodes_one_block

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        spend_bundle = generate_test_spend_bundle(wallet_a, coin)
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        await full_node_1.respond_transaction(tx, peer, test=True)

        await time_out_assert(
            10,
            full_node_1.full_node.mempool_manager.get_spendbundle,
            spend_bundle,
            spend_bundle.name(),
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode,lock_value,expected",
        [
            # the mempool rules don't allow relative height- or time conditions on
            # ephemeral spends
            (co.ASSERT_MY_BIRTH_HEIGHT, -1, mis.FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 0x100000000, mis.FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 5, mis.FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 6, mis.FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, -1, mis.FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 0x10000000000000000, mis.FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 10049, mis.FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 10050, mis.FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 10051, mis.FAILED),
            (co.ASSERT_SECONDS_RELATIVE, -2, mis.FAILED),
            (co.ASSERT_SECONDS_RELATIVE, -1, mis.FAILED),
            (co.ASSERT_SECONDS_RELATIVE, 0, mis.FAILED),
            (co.ASSERT_SECONDS_RELATIVE, 1, mis.FAILED),
            (co.ASSERT_HEIGHT_RELATIVE, -2, mis.FAILED),
            (co.ASSERT_HEIGHT_RELATIVE, -1, mis.FAILED),
            (co.ASSERT_HEIGHT_RELATIVE, 0, mis.FAILED),
            (co.ASSERT_HEIGHT_RELATIVE, 1, mis.FAILED),
            # the absolute height and seconds tests require fresh full nodes to
            # run the test on. The fixture (one_node_one_block) creates a block,
            # then condition_tester2 creates another 3 blocks
            (co.ASSERT_HEIGHT_ABSOLUTE, 4, mis.SUCCESS),
            (co.ASSERT_HEIGHT_ABSOLUTE, 5, mis.SUCCESS),
            (co.ASSERT_HEIGHT_ABSOLUTE, 6, mis.PENDING),
            (co.ASSERT_HEIGHT_ABSOLUTE, 7, mis.PENDING),
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_ABSOLUTE, 10049, mis.SUCCESS),
            (co.ASSERT_SECONDS_ABSOLUTE, 10050, mis.SUCCESS),
            (co.ASSERT_SECONDS_ABSOLUTE, 10051, mis.FAILED),
            (co.ASSERT_SECONDS_ABSOLUTE, 10052, mis.FAILED),
        ],
    )
    async def test_ephemeral_timelock(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
        opcode: ConditionOpcode,
        lock_value: int,
        expected: MempoolInclusionStatus,
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            conditions = {opcode: [ConditionWithArgs(opcode, [int_to_bytes(lock_value)])]}
            tx1 = wallet_a.generate_signed_transaction(uint64(1000000), wallet_a.get_new_puzzlehash(), coin_2)

            ephemeral_coin: Coin = tx1.additions()[0]
            tx2 = wallet_a.generate_signed_transaction(
                uint64(1000000), wallet_a.get_new_puzzlehash(), ephemeral_coin, conditions.copy(), uint64(0)
            )

            bundle = SpendBundle.aggregate([tx1, tx2])
            return bundle

        full_node_1, server_1, bt = one_node_one_block
        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        blocks, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        print(f"opcode={opcode} timelock_value={lock_value} expected={expected} status={status}")
        print(f"status: {status}")
        print(f"error: {err}")

        assert status == expected
        if expected == MempoolInclusionStatus.SUCCESS:
            assert mempool_bundle == bundle
            assert err is None
        else:
            assert mempool_bundle is None
            assert err is not None

    # this test makes sure that one spend successfully asserts the announce from
    # another spend, even though the assert condition is duplicated 100 times
    @pytest.mark.anyio
    async def test_coin_announcement_duplicate_consumed(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_2.name(), asserted_msg=b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.msg_calc])
            dic = {cvp.opcode: [cvp] * 100}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, server_1, bt = one_node_one_block
        blocks, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle == bundle
        assert status == MempoolInclusionStatus.SUCCESS

    # this test makes sure that one spend successfully asserts the announce from
    # another spend, even though the create announcement is duplicated 100 times
    @pytest.mark.anyio
    async def test_coin_duplicate_announcement_consumed(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_2.name(), asserted_msg=b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.msg_calc])
            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2] * 100}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, server_1, bt = one_node_one_block
        blocks, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle == bundle
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_double_spend(
        self,
        two_nodes_one_block: Tuple[FullNodeSimulator, FullNodeSimulator, ChiaServer, ChiaServer, BlockTools],
        wallet_a: WalletTool,
        self_hostname: str,
    ) -> None:
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2, bt = two_nodes_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        for block in blocks:
            await full_node_1.full_node.add_block(block)
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        spend_bundle1 = generate_test_spend_bundle(wallet_a, blocks[-1].get_included_reward_coins()[0])

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        status, err = await respond_transaction(full_node_1, tx1, peer, test=True)
        assert err is None
        assert status == MempoolInclusionStatus.SUCCESS

        spend_bundle2 = generate_test_spend_bundle(
            wallet_a,
            blocks[-1].get_included_reward_coins()[0],
            new_puzzle_hash=BURN_PUZZLE_HASH_2,
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle2)
        status, err = await respond_transaction(full_node_1, tx2, peer, test=True)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert err == Err.MEMPOOL_CONFLICT
        assert sb1 == spend_bundle1
        assert sb2 is None
        assert status == MempoolInclusionStatus.PENDING

    @pytest.mark.anyio
    async def test_double_spend_with_higher_fee(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, _, bt = one_node_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height if len(blocks) > 0 else -1
        reward_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)
        for block in blocks:
            await full_node_1.full_node.add_block(block)
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coins = iter(blocks[-1].get_included_reward_coins())
        coin1, coin2 = next(coins), next(coins)
        coins = iter(blocks[-2].get_included_reward_coins())
        coin3, coin4 = next(coins), next(coins)

        sb1_1 = await gen_and_send_sb(full_node_1, wallet_a, coin1)
        sb1_2 = await gen_and_send_sb(full_node_1, wallet_a, coin1, fee=uint64(1))

        # Fee increase is insufficient, the old spendbundle must stay
        assert_sb_in_pool(full_node_1.full_node.mempool_manager, sb1_1)
        assert_sb_not_in_pool(full_node_1.full_node.mempool_manager, sb1_2)
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

        sb1_3 = await gen_and_send_sb(full_node_1, wallet_a, coin1, fee=MEMPOOL_MIN_FEE_INCREASE)

        # Fee increase is sufficiently high, sb1_1 gets replaced with sb1_3
        assert_sb_not_in_pool(full_node_1.full_node.mempool_manager, sb1_1)
        assert_sb_in_pool(full_node_1.full_node.mempool_manager, sb1_3)
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

        sb2 = generate_test_spend_bundle(wallet_a, coin2, fee=MEMPOOL_MIN_FEE_INCREASE)
        sb12 = SpendBundle.aggregate([sb2, sb1_3])
        await send_sb(full_node_1, sb12)

        # Aggregated spendbundle sb12 replaces sb1_3 since it spends a superset
        # of coins spent in sb1_3
        assert_sb_in_pool(full_node_1.full_node.mempool_manager, sb12)
        assert_sb_not_in_pool(full_node_1.full_node.mempool_manager, sb1_3)
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

        sb3 = generate_test_spend_bundle(wallet_a, coin3, fee=uint64(MEMPOOL_MIN_FEE_INCREASE * 2))
        sb23 = SpendBundle.aggregate([sb2, sb3])
        await send_sb(full_node_1, sb23)

        # sb23 must not replace existing sb12 as the former does not spend all
        # coins that are spent in the latter (specifically, coin1)
        assert_sb_in_pool(full_node_1.full_node.mempool_manager, sb12)
        assert_sb_not_in_pool(full_node_1.full_node.mempool_manager, sb23)
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

        await send_sb(full_node_1, sb3)
        # Adding non-conflicting sb3 should succeed
        assert_sb_in_pool(full_node_1.full_node.mempool_manager, sb3)
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

        sb4_1 = generate_test_spend_bundle(wallet_a, coin4, fee=MEMPOOL_MIN_FEE_INCREASE)
        sb1234_1 = SpendBundle.aggregate([sb12, sb3, sb4_1])
        await send_sb(full_node_1, sb1234_1)
        # sb1234_1 should not be in pool as it decreases total fees per cost
        assert_sb_not_in_pool(full_node_1.full_node.mempool_manager, sb1234_1)
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

        sb4_2 = generate_test_spend_bundle(wallet_a, coin4, fee=uint64(MEMPOOL_MIN_FEE_INCREASE * 2))
        sb1234_2 = SpendBundle.aggregate([sb12, sb3, sb4_2])
        await send_sb(full_node_1, sb1234_2)
        # sb1234_2 has a higher fee per cost than its conflicts and should get
        # into mempool
        assert_sb_in_pool(full_node_1.full_node.mempool_manager, sb1234_2)
        assert_sb_not_in_pool(full_node_1.full_node.mempool_manager, sb12)
        assert_sb_not_in_pool(full_node_1.full_node.mempool_manager, sb3)
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

    @pytest.mark.anyio
    async def test_invalid_signature(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        reward_ph = wallet_a.get_new_puzzlehash()

        full_node_1, server_1, bt = one_node_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height if len(blocks) > 0 else -1
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        for block in blocks:
            await full_node_1.full_node.add_block(block)
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coins = iter(blocks[-1].get_included_reward_coins())
        coin1 = next(coins)

        sb: SpendBundle = generate_test_spend_bundle(wallet_a, coin1)
        assert sb.aggregated_signature != G2Element.generator()
        sb = sb.replace(aggregated_signature=G2Element.generator())
        res: Optional[Message] = await send_sb(full_node_1, sb)
        assert res is not None
        ack: TransactionAck = TransactionAck.from_bytes(res.data)
        assert ack.status == MempoolInclusionStatus.FAILED.value
        assert ack.error == Err.BAD_AGGREGATE_SIGNATURE.name
        invariant_check_mempool(full_node_1.full_node.mempool_manager.mempool)

    async def condition_tester(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
        dic: Dict[ConditionOpcode, List[ConditionWithArgs]],
        fee: int = 0,
        num_blocks: int = 3,
        coin: Optional[Coin] = None,
    ) -> Tuple[List[FullBlock], SpendBundle, WSChiaConnection, MempoolInclusionStatus, Optional[Err]]:
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, server_1, bt = one_node_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            num_blocks,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        _, dummy_node_id = await add_dummy_connection(server_1, bt.config["self_hostname"], 100)
        for node_id, wsc in server_1.all_connections.items():
            if node_id == dummy_node_id:
                dummy_peer = wsc
                break
        else:
            raise Exception("dummy peer not found")

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + num_blocks)

        spend_bundle1 = generate_test_spend_bundle(
            wallet_a, coin or list(blocks[-num_blocks + 2].get_included_reward_coins())[0], dic, uint64(fee)
        )

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx1, dummy_peer, test=True)
        return blocks, spend_bundle1, dummy_peer, status, err

    @pytest.mark.anyio
    async def condition_tester2(
        self,
        node_server_bt: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
        test_fun: Callable[[Coin, Coin], SpendBundle],
    ) -> Tuple[List[FullBlock], SpendBundle, MempoolInclusionStatus, Optional[Err]]:
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, server_1, bt = node_server_bt
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height if len(blocks) > 0 else -1
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            time_per_block=10,
        )
        _, dummy_node_id = await add_dummy_connection(server_1, bt.config["self_hostname"], 100)
        for node_id, wsc in server_1.all_connections.items():
            if node_id == dummy_node_id:
                dummy_peer = wsc
                break
        else:
            raise Exception("dummy peer not found")

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin_1 = blocks[-2].get_included_reward_coins()[0]
        coin_2 = blocks[-1].get_included_reward_coins()[0]

        bundle = test_fun(coin_1, coin_2)

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(bundle)
        status, err = await respond_transaction(full_node_1, tx1, dummy_peer, test=True)

        return blocks, bundle, status, err

    @pytest.mark.anyio
    async def test_invalid_block_index(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        cvp = ConditionWithArgs(
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            [int_to_bytes(start_height + 5)],
        )
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert err == Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
        assert status == MempoolInclusionStatus.PENDING

    @pytest.mark.anyio
    async def test_block_index_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert err == Err.INVALID_CONDITION
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_correct_block_index(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(1)])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_block_index_garbage(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        # garbage at the end of the argument list is ignored in consensus mode,
        # but not in mempool-mode
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(1), b"garbage"])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_negative_block_index(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(-1)])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_invalid_block_age(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(5)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_HEIGHT_RELATIVE_FAILED
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.PENDING

    @pytest.mark.anyio
    async def test_block_age_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_correct_block_age(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, num_blocks=4
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_block_age_garbage(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        # garbage at the end of the argument list is ignored in consensus mode,
        # but not in mempool mode
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(1), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, num_blocks=4
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_negative_block_age(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, num_blocks=4
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_correct_my_id(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin.name()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_my_id_garbage(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the argument list is ignored in consensus mode,
        # but not in mempool mode
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin.name(), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_invalid_my_id(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        coin_2 = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin_2.name()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_MY_COIN_ID_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_my_id_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_time_exceeds(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, _, _ = one_node_one_block
        blockchain_peak = full_node_1.full_node.blockchain.get_peak()
        assert blockchain_peak is not None
        assert blockchain_peak.timestamp is not None
        # 5 seconds should be before the next block
        time_now = blockchain_peak.timestamp + 5

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        _, spend_bundle1, _, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_assert_time_fail(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, _, _ = one_node_one_block
        blockchain_peak = full_node_1.full_node.blockchain.get_peak()
        assert blockchain_peak is not None
        assert blockchain_peak.timestamp is not None
        time_now = blockchain_peak.timestamp + 1000

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        _, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_SECONDS_ABSOLUTE_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_height_pending(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, _, _ = one_node_one_block
        blockchain_peak = full_node_1.full_node.blockchain.get_peak()
        assert blockchain_peak is not None
        current_height = blockchain_peak.height

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(current_height + 4)])
        dic = {cvp.opcode: [cvp]}
        _, spend_bundle1, _, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.PENDING

    @pytest.mark.anyio
    async def test_assert_time_negative(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        time_now = -1

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_assert_time_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_time_garbage(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, _, _ = one_node_one_block
        blockchain_peak = full_node_1.full_node.blockchain.get_peak()
        assert blockchain_peak is not None
        assert blockchain_peak.timestamp is not None
        time_now = blockchain_peak.timestamp + 5

        # garbage at the end of the argument list is ignored in consensus mode,
        # but not in mempool mode
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        _, spend_bundle1, _, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_time_relative_exceeds(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        time_relative = 3

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_SECONDS_RELATIVE_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

        for i in range(0, 4):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx2, peer, test=True)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_assert_time_relative_garbage(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        time_relative = 0

        # garbage at the end of the arguments is ignored in consensus mode, but
        # not in mempool mode
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_time_relative_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_time_relative_negative(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        time_relative = -3

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    # ensure one spend can assert a coin announcement from another spend
    @pytest.mark.anyio
    async def test_correct_coin_announcement_consumed(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_2.name(), asserted_msg=b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.msg_calc])
            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, server_1, bt = one_node_one_block
        blocks, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle == bundle
        assert status == MempoolInclusionStatus.SUCCESS

    # ensure one spend can assert a coin announcement from another spend, even
    # though the conditions have garbage at the end
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "assert_garbage,announce_garbage,expected,expected_included",
        [
            (True, False, Err.INVALID_CONDITION, MempoolInclusionStatus.FAILED),
            (False, True, Err.INVALID_CONDITION, MempoolInclusionStatus.FAILED),
            (False, False, None, MempoolInclusionStatus.SUCCESS),
        ],
    )
    async def test_coin_announcement_garbage(
        self,
        assert_garbage: bool,
        announce_garbage: bool,
        expected: Optional[Err],
        expected_included: MempoolInclusionStatus,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_2.name(), asserted_msg=b"test")
            # garbage at the end is ignored in consensus mode, but not in
            # mempool mode
            cvp = ConditionWithArgs(
                ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
                [bytes(announce.msg_calc)] + ([b"garbage"] if announce_garbage else []),
            )
            dic = {cvp.opcode: [cvp]}

            # garbage at the end is ignored in consensus mode, but not in
            # mempool mode
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"] + ([b"garbage"] if assert_garbage else [])
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, server_1, bt = one_node_one_block
        blocks, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        assert err is expected
        assert status == expected_included
        if status == MempoolInclusionStatus.SUCCESS:
            mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())
            assert mempool_bundle == bundle

    @pytest.mark.anyio
    async def test_coin_announcement_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            # missing arg here
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [])
            dic = {cvp.opcode: [cvp]}
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        assert err == Err.INVALID_CONDITION
        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_coin_announcement_missing_arg2(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_2.name(), asserted_msg=b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.msg_calc])
            dic = {cvp.opcode: [cvp]}
            # missing arg here
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        assert err == Err.INVALID_CONDITION
        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_coin_announcement_too_big(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_2.name(), asserted_msg=bytes([1] * 10000))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.msg_calc])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, bt = one_node_one_block
        blocks, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=bundle
        )
        try:
            await _validate_and_add_block(full_node_1.full_node.blockchain, blocks[-1])
            assert False
        except AssertionError as e:
            assert e.args[0] == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    # ensure an assert coin announcement is rejected if it doesn't match the
    # create announcement
    @pytest.mark.anyio
    async def test_invalid_coin_announcement_rejected(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_2.name(), asserted_msg=b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.msg_calc])

            dic = {cvp.opcode: [cvp]}
            # mismatching message
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
                [b"wrong test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_invalid_coin_announcement_rejected_two(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertCoinAnnouncement(asserted_id=coin_1.name(), asserted_msg=b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.msg_calc])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            # coin 2 is making the announcement, right message wrong coin
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_correct_puzzle_announcement(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertPuzzleAnnouncement(asserted_ph=coin_2.puzzle_hash, asserted_msg=bytes(0x80))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.msg_calc])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [bytes(0x80)])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle == bundle
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "assert_garbage,announce_garbage,expected,expected_included",
        [
            (True, False, Err.INVALID_CONDITION, MempoolInclusionStatus.FAILED),
            (False, True, Err.INVALID_CONDITION, MempoolInclusionStatus.FAILED),
            (False, False, None, MempoolInclusionStatus.SUCCESS),
        ],
    )
    async def test_puzzle_announcement_garbage(
        self,
        assert_garbage: bool,
        announce_garbage: bool,
        expected: Optional[Err],
        expected_included: MempoolInclusionStatus,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertPuzzleAnnouncement(asserted_ph=coin_2.puzzle_hash, asserted_msg=bytes(0x80))

            # garbage at the end is ignored in consensus mode, but not in
            # mempool mode
            cvp = ConditionWithArgs(
                ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
                [bytes(announce.msg_calc)] + ([b"garbage"] if assert_garbage else []),
            )
            dic = {cvp.opcode: [cvp]}
            # garbage at the end is ignored in consensus mode, but not in
            # mempool mode
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [bytes(0x80)] + ([b"garbage"] if announce_garbage else [])
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        assert err is expected
        assert status == expected_included
        if status == MempoolInclusionStatus.SUCCESS:
            mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())
            assert mempool_bundle == bundle

    @pytest.mark.anyio
    async def test_puzzle_announcement_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            # missing arg here
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [])
            dic = {cvp.opcode: [cvp]}
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [b"test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.INVALID_CONDITION
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_puzzle_announcement_missing_arg2(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertPuzzleAnnouncement(asserted_ph=coin_2.puzzle_hash, asserted_msg=b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.msg_calc])
            dic = {cvp.opcode: [cvp]}
            # missing arg here
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.INVALID_CONDITION
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_invalid_puzzle_announcement_rejected(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertPuzzleAnnouncement(asserted_ph=coin_2.puzzle_hash, asserted_msg=bytes("test", "utf-8"))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.msg_calc])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [b"wrong test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_invalid_puzzle_announcement_rejected_two(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = AssertPuzzleAnnouncement(asserted_ph=coin_2.puzzle_hash, asserted_msg=bytes(0x80))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.msg_calc])

            dic = {cvp.opcode: [cvp]}
            # Wrong type of Create_announcement
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
                [b"test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        full_node_1, _, _ = one_node_one_block
        _, bundle, status, err = await self.condition_tester2(one_node_one_block, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_fee_condition(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, fee=10
        )
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert mempool_bundle is not None
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_assert_fee_condition_garbage(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        # garbage at the end of the arguments is ignored in consensus mode, but
        # not in mempool mode
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, fee=10
        )
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is Err.INVALID_CONDITION
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_fee_condition_missing_arg(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, fee=10
        )
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.INVALID_CONDITION
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_assert_fee_condition_negative_fee(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, fee=10
        )
        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert status == MempoolInclusionStatus.FAILED
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle1
        )
        assert full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name()) is None
        await _validate_and_add_block(
            full_node_1.full_node.blockchain, blocks[-1], expected_error=Err.RESERVE_FEE_CONDITION_FAILED
        )

    @pytest.mark.anyio
    async def test_assert_fee_condition_fee_too_large(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(2**64)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, fee=10
        )
        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert status == MempoolInclusionStatus.FAILED
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle1
        )
        assert full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name()) is None
        await _validate_and_add_block(
            full_node_1.full_node.blockchain, blocks[-1], expected_error=Err.RESERVE_FEE_CONDITION_FAILED
        )

    @pytest.mark.anyio
    async def test_assert_fee_condition_wrong_fee(
        self, one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools], wallet_a: WalletTool
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic, fee=9)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_stealing_fee(
        self,
        two_nodes_one_block: Tuple[FullNodeSimulator, FullNodeSimulator, ChiaServer, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, _, server_1, server_2, bt = two_nodes_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            5,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        peer = await connect_and_get_peer(server_1, server_2, bt.config["self_hostname"])

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 5)

        receiver_puzzlehash = BURN_PUZZLE_HASH

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}

        fee = 9

        coin_1 = blocks[-2].get_included_reward_coins()[0]
        coin_2 = None
        for coin in blocks[-1].get_included_reward_coins():
            if coin.amount == coin_1.amount:
                coin_2 = coin
        assert coin_2 is not None
        spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic, uint64(fee))

        steal_fee_spendbundle = wallet_a.generate_signed_transaction(
            uint64(coin_1.amount + fee - 4), receiver_puzzlehash, coin_2
        )

        assert spend_bundle1 is not None
        assert steal_fee_spendbundle is not None

        combined = SpendBundle.aggregate([spend_bundle1, steal_fee_spendbundle])

        assert estimate_fees(combined) == 4

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx1, peer, test=True)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_double_spend_same_bundle(
        self,
        two_nodes_one_block: Tuple[FullNodeSimulator, FullNodeSimulator, ChiaServer, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, _, server_1, server_2, bt = two_nodes_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)
        # coin = blocks[-1].get_included_reward_coins()[0]
        # spend_bundle1 = generate_test_spend_bundle(wallet_a, coin)
        coin = await next_block(full_node_1, wallet_a, bt)
        spend_bundle1 = generate_test_spend_bundle(wallet_a, coin)

        assert spend_bundle1 is not None

        spend_bundle2 = generate_test_spend_bundle(
            wallet_a,
            coin,
            new_puzzle_hash=BURN_PUZZLE_HASH_2,
        )

        assert spend_bundle2 is not None

        spend_bundle_combined = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx = full_node_protocol.RespondTransaction(spend_bundle_combined)

        peer = await connect_and_get_peer(server_1, server_2, bt.config["self_hostname"])
        status, err = await respond_transaction(full_node_1, tx, peer, test=True)

        sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle_combined.name())
        assert err == Err.DOUBLE_SPEND
        assert sb is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_agg_sig_condition(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, server_1, bt = one_node_one_block
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin = await next_block(full_node_1, wallet_a, bt)
        # coin = blocks[-1].get_included_reward_coins()[0]
        spend_bundle_0 = generate_test_spend_bundle(wallet_a, coin)
        unsigned: List[CoinSpend] = spend_bundle_0.coin_spends

        assert len(unsigned) == 1
        # coin_spend: CoinSpend = unsigned[0]

        # TODO(straya): fix this test
        # puzzle, solution = list(coin_spend.solution.as_iter())
        # conditions_dict = conditions_dict_for_solution(coin_spend.puzzle_reveal, coin_spend.solution, INFINITE_COST)

        # pkm_pairs = pkm_pairs_for_conditions_dict(conditions_dict, coin_spend.coin.name())
        # assert len(pkm_pairs) == 1
        #
        # assert pkm_pairs[0][1] == solution.rest().first().get_tree_hash() + coin_spend.coin.name()
        #
        # spend_bundle = wallet_a.sign_transaction(unsigned)
        # assert spend_bundle is not None
        #
        # tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        # await full_node_1.add_transaction(tx, peer, test=True)
        #
        # sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle.name())
        # assert sb is spend_bundle

    @pytest.mark.anyio
    async def test_correct_my_parent(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin.parent_coin_info])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_my_parent_garbage(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the arguments list is allowed in consensus mode,
        # but not in mempool mode
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin.parent_coin_info, b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_my_parent_missing_arg(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_invalid_my_parent(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        coin_2 = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin_2.parent_coin_info])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_PARENT_ID_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_correct_my_puzhash(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [coin.puzzle_hash])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_my_puzhash_garbage(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the arguments list is allowed but stripped
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [coin.puzzle_hash, b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_my_puzhash_missing_arg(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_invalid_my_puzhash(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [Program.to([]).get_tree_hash()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_PUZZLEHASH_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_correct_my_amount(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(coin.amount)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 == spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_my_amount_garbage(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block

        _ = await next_block(full_node_1, wallet_a, bt)
        _ = await next_block(full_node_1, wallet_a, bt)
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the arguments list is allowed in consensus mode,
        # but not in mempool mode
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(coin.amount), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            one_node_one_block, wallet_a, dic, coin=coin
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_my_amount_missing_arg(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_invalid_my_amount(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(1000)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_AMOUNT_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_negative_my_amount(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, server_1, bt = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_AMOUNT_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.anyio
    async def test_my_amount_too_large(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, _, _ = one_node_one_block
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(2**64)])
        dic = {cvp.opcode: [cvp]}
        _, spend_bundle1, _, status, err = await self.condition_tester(one_node_one_block, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_AMOUNT_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED


# the following tests generate generator programs and run them through get_name_puzzle_conditions()

COST_PER_BYTE = 12000
MAX_BLOCK_COST_CLVM = 11000000000


def generator_condition_tester(
    conditions: str,
    *,
    mempool_mode: bool = False,
    quote: bool = True,
    max_cost: int = MAX_BLOCK_COST_CLVM,
    height: uint32,
    coin_amount: int = 123,
) -> NPCResult:
    prg = f"(q ((0x0101010101010101010101010101010101010101010101010101010101010101 {'(q ' if quote else ''} {conditions} {')' if quote else ''} {coin_amount} (() (q . ())))))"  # noqa
    print(f"program: {prg}")
    program = SerializedProgram.from_bytes(binutils.assemble(prg).as_bin())
    generator = BlockGenerator(program, [])
    print(f"len: {len(bytes(program))}")
    npc_result: NPCResult = get_name_puzzle_conditions(
        generator, max_cost, mempool_mode=mempool_mode, height=height, constants=test_constants
    )
    return npc_result


class TestGeneratorConditions:
    def test_invalid_condition_args_terminator(self, softfork_height: uint32) -> None:
        # note how the condition argument list isn't correctly terminated with a
        # NIL atom. This is allowed, and all arguments beyond the ones we look
        # at are ignored, including the termination of the list
        npc_result = generator_condition_tester("(80 50 . 1)", height=softfork_height)
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1
        assert npc_result.conds.spends[0].seconds_relative == 50

    @pytest.mark.parametrize(
        "mempool,operand",
        [
            (True, -1),
            (False, -1),
            (True, 1),
            (False, 1),
        ],
    )
    def test_div(self, mempool: bool, operand: int, softfork_height: uint32) -> None:
        # op_div is disallowed on negative numbers in the mempool, and after the
        # softfork
        npc_result = generator_condition_tester(
            f"(c (c (q . 80) (c (/ (q . 50) (q . {operand})) ())) ())",
            quote=False,
            mempool_mode=mempool,
            height=softfork_height,
        )

        # after the 2.0 hard fork, division with negative numbers is allowed
        assert npc_result.error is None

    def test_invalid_condition_list_terminator(self, softfork_height: uint32) -> None:
        # note how the list of conditions isn't correctly terminated with a
        # NIL atom. This is a failure
        npc_result = generator_condition_tester("(80 50) . 3", height=softfork_height)
        assert npc_result.error in [Err.INVALID_CONDITION.value, Err.GENERATOR_RUNTIME_ERROR.value]

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_height_time_conditions(self, opcode: ConditionOpcode, softfork_height: uint32) -> None:
        # even though the generator outputs multiple conditions, we only
        # need to return the highest one (i.e. most strict)
        npc_result = generator_condition_tester(
            " ".join([f"({opcode.value[0]} {i})" for i in range(50, 101)]), height=softfork_height
        )
        print(npc_result)
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1

        assert len(npc_result.conds.spends) == 1
        if opcode == ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
            assert npc_result.conds.height_absolute == 100
        elif opcode == ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
            assert npc_result.conds.spends[0].height_relative == 100
        elif opcode == ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
            assert npc_result.conds.seconds_absolute == 100
        elif opcode == ConditionOpcode.ASSERT_SECONDS_RELATIVE:
            assert npc_result.conds.spends[0].seconds_relative == 100

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
            ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
        ],
    )
    def test_just_announcement(self, opcode: ConditionOpcode, softfork_height: uint32) -> None:
        message = "a" * 1024
        # announcements are validated on the Rust side and never returned
        # back. They are either satisified or cause an immediate failure
        npc_result = generator_condition_tester(f'({opcode.value[0]} "{message}") ' * 50, height=softfork_height)
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1
        # create-announcements and assert-announcements are dropped once
        # validated

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
            ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
        ],
    )
    def test_assert_announcement_fail(self, opcode: ConditionOpcode, softfork_height: uint32) -> None:
        message = "a" * 1024
        # announcements are validated on the Rust side and never returned
        # back. They ar either satisified or cause an immediate failure
        # in this test we just assert announcements, we never make them, so
        # these should fail
        npc_result = generator_condition_tester(f'({opcode.value[0]} "{message}") ', height=softfork_height)
        print(npc_result)
        assert npc_result.error == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED.value

    def test_multiple_reserve_fee(self, softfork_height: uint32) -> None:
        # RESERVE_FEE
        cond = 52
        # even though the generator outputs 3 conditions, we only need to return one copy
        # with all the fees accumulated
        npc_result = generator_condition_tester(f"({cond} 10) " * 3, height=softfork_height)
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert npc_result.conds.reserve_fee == 30
        assert len(npc_result.conds.spends) == 1

    def test_duplicate_outputs(self, softfork_height: uint32) -> None:
        # CREATE_COIN
        # creating multiple coins with the same properties (same parent, same
        # target puzzle hash and same amount) is not allowed. That's a consensus
        # failure.
        puzzle_hash = "abababababababababababababababab"
        npc_result = generator_condition_tester(f'(51 "{puzzle_hash}" 10) ' * 2, height=softfork_height)
        assert npc_result.error == Err.DUPLICATE_OUTPUT.value

    def test_create_coin_cost(self, softfork_height: uint32) -> None:
        # CREATE_COIN
        puzzle_hash = "abababababababababababababababab"

        if softfork_height >= test_constants.HARD_FORK_HEIGHT:
            generator_base_cost = 40
        else:
            generator_base_cost = 20470

        # this max cost is exactly enough for the create coin condition
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash}" 10) ',
            max_cost=generator_base_cost + 95 * COST_PER_BYTE + ConditionCost.CREATE_COIN.value,
            height=softfork_height,
        )
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert npc_result.conds.cost == generator_base_cost + 95 * COST_PER_BYTE + ConditionCost.CREATE_COIN.value
        assert len(npc_result.conds.spends) == 1
        assert len(npc_result.conds.spends[0].create_coin) == 1

        # if we subtract one from max cost, this should fail
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash}" 10) ',
            max_cost=generator_base_cost + 95 * COST_PER_BYTE + ConditionCost.CREATE_COIN.value - 1,
            height=softfork_height,
        )
        assert npc_result.error in [Err.BLOCK_COST_EXCEEDS_MAX.value, Err.INVALID_BLOCK_COST.value]

    @pytest.mark.parametrize(
        "condition",
        [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_ME,
        ],
    )
    def test_agg_sig_cost(self, condition: ConditionOpcode, softfork_height: uint32) -> None:
        pubkey = "0x" + bytes(G1Element.generator()).hex()

        if softfork_height >= test_constants.HARD_FORK_HEIGHT:
            generator_base_cost = 40
        else:
            generator_base_cost = 20512

        expected_cost = ConditionCost.AGG_SIG.value

        # this max cost is exactly enough for the AGG_SIG condition
        npc_result = generator_condition_tester(
            f'({condition[0]} {pubkey} "foobar") ',
            max_cost=generator_base_cost + 117 * COST_PER_BYTE + expected_cost,
            height=softfork_height,
        )
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert npc_result.conds.cost == generator_base_cost + 117 * COST_PER_BYTE + expected_cost
        assert len(npc_result.conds.spends) == 1

        # if we subtract one from max cost, this should fail
        npc_result = generator_condition_tester(
            f'({condition[0]} {pubkey} "foobar") ',
            max_cost=generator_base_cost + 117 * COST_PER_BYTE + expected_cost - 1,
            height=softfork_height,
        )
        assert npc_result.error in [
            Err.GENERATOR_RUNTIME_ERROR.value,
            Err.BLOCK_COST_EXCEEDS_MAX.value,
            Err.INVALID_BLOCK_COST.value,
        ]

    @pytest.mark.parametrize(
        "condition",
        [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_ME,
        ],
    )
    @pytest.mark.parametrize("extra_arg", [' "baz"', ""])
    @pytest.mark.parametrize("mempool", [True, False])
    def test_agg_sig_extra_arg(
        self, condition: ConditionOpcode, extra_arg: str, mempool: bool, softfork_height: uint32
    ) -> None:
        pubkey = "0x" + bytes(G1Element.generator()).hex()

        # in mempool mode, we don't allow extra arguments
        if mempool and extra_arg != "":
            expected_error = Err.INVALID_CONDITION.value
        else:
            expected_error = None

        # this max cost is exactly enough for the AGG_SIG condition
        npc_result = generator_condition_tester(
            f'({condition[0]} {pubkey} "foobar"{extra_arg}) ',
            max_cost=11000000000,
            height=softfork_height,
            mempool_mode=mempool,
        )
        assert npc_result.error == expected_error
        if npc_result.error is None:
            assert npc_result.conds is not None
            assert len(npc_result.conds.spends) == 1
        else:
            assert npc_result.conds is None

    def test_create_coin_different_parent(self, softfork_height: uint32) -> None:
        # if the coins we create have different parents, they are never
        # considered duplicate, even when they have the same puzzle hash and
        # amount
        puzzle_hash = "abababababababababababababababab"
        program = SerializedProgram.from_bytes(
            binutils.assemble(
                f'(q ((0x0101010101010101010101010101010101010101010101010101010101010101 (q (51 "{puzzle_hash}" 10)) 123 (() (q . ())))(0x0101010101010101010101010101010101010101010101010101010101010102 (q (51 "{puzzle_hash}" 10)) 123 (() (q . ()))) ))'  # noqa
            ).as_bin()
        )
        generator = BlockGenerator(program, [])
        npc_result: NPCResult = get_name_puzzle_conditions(
            generator, MAX_BLOCK_COST_CLVM, mempool_mode=False, height=softfork_height, constants=test_constants
        )
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 2
        for s in npc_result.conds.spends:
            assert s.create_coin == [(puzzle_hash.encode("ascii"), 10, None)]

    def test_create_coin_different_puzzhash(self, softfork_height: uint32) -> None:
        # CREATE_COIN
        # coins with different puzzle hashes are not considered duplicate
        puzzle_hash_1 = "abababababababababababababababab"
        puzzle_hash_2 = "cbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcb"
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash_1}" 5) (51 "{puzzle_hash_2}" 5)', height=softfork_height
        )
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1
        assert (puzzle_hash_1.encode("ascii"), 5, None) in npc_result.conds.spends[0].create_coin
        assert (puzzle_hash_2.encode("ascii"), 5, None) in npc_result.conds.spends[0].create_coin

    def test_create_coin_different_amounts(self, softfork_height: uint32) -> None:
        # CREATE_COIN
        # coins with different amounts are not considered duplicate
        puzzle_hash = "abababababababababababababababab"
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash}" 5) (51 "{puzzle_hash}" 4)', height=softfork_height
        )
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1
        coins = npc_result.conds.spends[0].create_coin
        assert (puzzle_hash.encode("ascii"), 5, None) in coins
        assert (puzzle_hash.encode("ascii"), 4, None) in coins

    def test_create_coin_with_hint(self, softfork_height: uint32) -> None:
        # CREATE_COIN
        puzzle_hash_1 = "abababababababababababababababab"
        hint = "12341234123412341234213421341234"
        npc_result = generator_condition_tester(f'(51 "{puzzle_hash_1}" 5 ("{hint}"))', height=softfork_height)
        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1
        coins = npc_result.conds.spends[0].create_coin
        assert coins == [(puzzle_hash_1.encode("ascii"), 5, hint.encode("ascii"))]

    @pytest.mark.parametrize("mempool", [True, False])
    @pytest.mark.parametrize(
        "condition",
        [
            '(2 100 "foo" "bar")',
            "(100)",
            "(4 1) (2 2) (3 3)",
            '("foobar")',
            '(0x100 "foobar")',
            '(0x1ff "foobar")',
        ],
    )
    def test_unknown_condition(self, mempool: bool, condition: str, softfork_height: uint32) -> None:
        npc_result = generator_condition_tester(condition, mempool_mode=mempool, height=softfork_height)
        print(npc_result)
        if mempool:
            assert npc_result.error == Err.INVALID_CONDITION.value
        else:
            assert npc_result.error is None

    @pytest.mark.parametrize("mempool", [True, False])
    @pytest.mark.parametrize(
        "condition, expect_error",
        [
            # the softfork condition must include at least 1 argument to
            # indicate its cost
            ("(90)", Err.INVALID_CONDITION.value),
            ("(90 1000000)", None),
        ],
    )
    def test_softfork_condition(
        self, mempool: bool, condition: str, expect_error: Optional[int], softfork_height: uint32
    ) -> None:
        npc_result = generator_condition_tester(condition, mempool_mode=mempool, height=softfork_height)
        print(npc_result)

        # in mempool all unknown conditions are always a failure
        if mempool:
            expect_error = Err.INVALID_CONDITION.value

        assert npc_result.error == expect_error

    @pytest.mark.parametrize("mempool", [True, False])
    @pytest.mark.parametrize(
        "condition, expect_error",
        [
            ('(66 0 "foo") (67 0 "bar")', Err.MESSAGE_NOT_SENT_OR_RECEIVED.value),
            ('(66 0 "foo") (67 0 "foo")', None),
        ],
    )
    def test_message_condition(
        self, mempool: bool, condition: str, expect_error: Optional[int], softfork_height: uint32
    ) -> None:
        npc_result = generator_condition_tester(condition, mempool_mode=mempool, height=softfork_height)
        print(npc_result)
        assert npc_result.error == expect_error


# the tests below are malicious generator programs

# this program:
# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c V (iter V (- N 1))) ())
#  )
#  (iter (c (q . 83) (c (concat (large_string 0x00 A) (q . 100)) ())) B)
# )
# with A=28 and B specified as {num}

SINGLE_ARG_INT_COND = "(a (q 2 4 (c 2 (c (c (q . {opcode}) (c (concat (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (q . {val})) ())) (c 11 ())))) (c (q (a (i 11 (q 4 5 (a 4 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 28 {num})))"  # noqa

# this program:
# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c (c (q . 83) (c V ())) (iter (substr V 1) (- N 1))) ())
#  )
#  (iter (concat (large_string 0x00 A) (q . 100)) B)
# )
# truncates the first byte of the large string being passed down for each
# iteration, in an attempt to defeat any caching of integers by node ID.
# substr is cheap, and no memory is copied, so we can perform a lot of these
SINGLE_ARG_INT_SUBSTR_COND = "(a (q 2 4 (c 2 (c (concat (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (q . {val})) (c 11 ())))) (c (q (a (i 11 (q 4 (c (q . {opcode}) (c 5 ())) (a 4 (c 2 (c (substr 5 (q . 1)) (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 28 {num})))"  # noqa

# this program:
# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c (c (q . 83) (c V ())) (iter (substr V 0 (- (strlen V) 1)) (- N 1))) ())
#  )
#  (iter (concat (large_string 0x00 A) (q . 0xffffffff)) B)
# )
SINGLE_ARG_INT_SUBSTR_TAIL_COND = "(a (q 2 4 (c 2 (c (concat (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (q . {val})) (c 11 ())))) (c (q (a (i 11 (q 4 (c (q . {opcode}) (c 5 ())) (a 4 (c 2 (c (substr 5 () (- (strlen 5) (q . 1))) (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 25 {num})))"  # noqa

# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c (c (q . 83) (c (concat V N) ())) (iter V (- N 1))) ())
#  )
#  (iter (large_string 0x00 A) B)
# )
SINGLE_ARG_INT_LADDER_COND = "(a (q 2 4 (c 2 (c (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (c 11 ())))) (c (q (a (i 11 (q 4 (c (q . {opcode}) (c (concat 5 11) ())) (a 4 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 24 {num})))"  # noqa

# this program:
# (mod (A B)
#  (defun large_message (N)
#    (lsh (q . "a") N)
#  )
#  (defun iter (V N)
#    (if N (c V (iter V (- N 1))) ())
#  )
#  (iter (c (q . 60) (c (large_message A) ())) B)
# )
# with B set to {num}

CREATE_ANNOUNCE_COND = "(a (q 2 4 (c 2 (c (c (q . {opcode}) (c (a 6 (c 2 (c 5 ()))) ())) (c 11 ())))) (c (q (a (i 11 (q 4 5 (a 4 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) 23 (q . 97) 5) (q 8184 {num})))"  # noqa

# this program:
# (mod (A)
#  (defun iter (V N)
#    (if N (c V (iter V (- N 1))) ())
#  )
#  (iter (q 51 "abababababababababababababababab" 1) A)
# )
CREATE_COIN = '(a (q 2 2 (c 2 (c (q 51 "abababababababababababababababab" 1) (c 5 ())))) (c (q 2 (i 11 (q 4 5 (a 2 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) (q {num})))'  # noqa

# this program:
# (mod (A)
#   (defun append (L B)
#     (if L
#       (c (f L) (append (r L) B))
#       (c B ())
#     )
#   )
#   (defun iter (V N)
#     (if N (c (append V N) (iter V (- N 1))) ())
#   )
#   (iter (q 51 "abababababababababababababababab") A)
# )
# creates {num} CREATE_COIN conditions, each with a different amount
CREATE_UNIQUE_COINS = '(a (q 2 6 (c 2 (c (q 51 "abababababababababababababababab") (c 5 ())))) (c (q (a (i 5 (q 4 9 (a 4 (c 2 (c 13 (c 11 ()))))) (q 4 11 ())) 1) 2 (i 11 (q 4 (a 4 (c 2 (c 5 (c 11 ())))) (a 6 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) (q {num})))'  # noqa


# some of the malicious tests will fail post soft-fork, this function helps test
# the specific error to expect
def error_for_condition(cond: ConditionOpcode) -> int:
    if cond == ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED.value
    if cond == ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
        return Err.ASSERT_HEIGHT_RELATIVE_FAILED.value
    if cond == ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED.value
    if cond == ConditionOpcode.ASSERT_SECONDS_RELATIVE:
        return Err.ASSERT_SECONDS_RELATIVE_FAILED.value
    if cond == ConditionOpcode.RESERVE_FEE:
        return Err.RESERVE_FEE_CONDITION_FAILED.value
    assert False


class TestMaliciousGenerators:
    # TODO: create a lot of announcements. The messages can be made different by
    # using substr on a large buffer

    # for all the height/time locks, we should only return the most strict
    # condition, not all of them
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_ladder(
        self, opcode: ConditionOpcode, softfork_height: uint32, benchmark_runner: BenchmarkRunner
    ) -> None:
        condition = SINGLE_ARG_INT_LADDER_COND.format(opcode=opcode.value[0], num=28, filler="0x00")

        with benchmark_runner.assert_runtime(seconds=1):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error == error_for_condition(opcode)

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer(
        self, opcode: ConditionOpcode, softfork_height: uint32, benchmark_runner: BenchmarkRunner
    ) -> None:
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0x00")

        with benchmark_runner.assert_runtime(seconds=3):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error == error_for_condition(opcode)

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_substr(
        self, opcode: ConditionOpcode, softfork_height: uint32, benchmark_runner: BenchmarkRunner
    ) -> None:
        condition = SINGLE_ARG_INT_SUBSTR_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0x00")

        with benchmark_runner.assert_runtime(seconds=2):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error == error_for_condition(opcode)

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_substr_tail(
        self, opcode: ConditionOpcode, softfork_height: uint32, benchmark_runner: BenchmarkRunner
    ) -> None:
        condition = SINGLE_ARG_INT_SUBSTR_TAIL_COND.format(
            opcode=opcode.value[0], num=280, val="0xffffffff", filler="0x00"
        )

        with benchmark_runner.assert_runtime(seconds=1):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error == error_for_condition(opcode)

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_negative(
        self, opcode: ConditionOpcode, softfork_height: uint32, benchmark_runner: BenchmarkRunner
    ) -> None:
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0xff")

        with benchmark_runner.assert_runtime(seconds=2.75):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1

    def test_duplicate_reserve_fee(self, softfork_height: uint32, benchmark_runner: BenchmarkRunner) -> None:
        opcode = ConditionOpcode.RESERVE_FEE
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0x00")

        with benchmark_runner.assert_runtime(seconds=1.5):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error == error_for_condition(opcode)

    def test_duplicate_reserve_fee_negative(self, softfork_height: uint32, benchmark_runner: BenchmarkRunner) -> None:
        opcode = ConditionOpcode.RESERVE_FEE
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=200000, val=100, filler="0xff")

        with benchmark_runner.assert_runtime(seconds=1.5):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        # RESERVE_FEE conditions fail unconditionally if they have a negative
        # amount
        assert npc_result.error == Err.RESERVE_FEE_CONDITION_FAILED.value
        assert npc_result.conds is None

    @pytest.mark.parametrize(
        "opcode", [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]
    )
    def test_duplicate_coin_announces(
        self, opcode: ConditionOpcode, softfork_height: uint32, benchmark_runner: BenchmarkRunner
    ) -> None:
        # we only allow 1024 create- or assert announcements per spend
        condition = CREATE_ANNOUNCE_COND.format(opcode=opcode.value[0], num=1024)

        with benchmark_runner.assert_runtime(seconds=14):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1
        # coin announcements are not propagated to python, but validated in rust
        # TODO: optimize clvm to make this run in < 1 second

    def test_create_coin_duplicates(self, softfork_height: uint32, benchmark_runner: BenchmarkRunner) -> None:
        # CREATE_COIN
        # this program will emit 6000 identical CREATE_COIN conditions. However,
        # we'll just end up looking at two of them, and fail at the first
        # duplicate
        condition = CREATE_COIN.format(num=600000)

        with benchmark_runner.assert_runtime(seconds=1.5):
            npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)

        assert npc_result.error == Err.DUPLICATE_OUTPUT.value
        assert npc_result.conds is None

    def test_many_create_coin(self, softfork_height: uint32, benchmark_runner: BenchmarkRunner) -> None:
        # CREATE_COIN
        # this program will emit many CREATE_COIN conditions, all with different
        # amounts.
        # the number 6095 was chosen carefully to not exceed the maximum cost
        condition = CREATE_UNIQUE_COINS.format(num=6094)

        with benchmark_runner.assert_runtime(seconds=0.3):
            npc_result = generator_condition_tester(
                condition, quote=False, height=softfork_height, coin_amount=123000000
            )

        assert npc_result.error is None
        assert npc_result.conds is not None
        assert len(npc_result.conds.spends) == 1
        spend = npc_result.conds.spends[0]
        assert len(spend.create_coin) == 6094

    @pytest.mark.anyio
    async def test_invalid_coin_spend_coin(
        self,
        one_node_one_block: Tuple[FullNodeSimulator, ChiaServer, BlockTools],
        wallet_a: WalletTool,
    ) -> None:
        full_node_1, _, bt = one_node_one_block
        reward_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            5,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, blocks[-1].height)

        spend_bundle = generate_test_spend_bundle(wallet_a, blocks[-1].get_included_reward_coins()[0])
        cs = spend_bundle.coin_spends[0]
        c = cs.coin
        coin_0 = Coin(c.parent_coin_info, bytes32([1] * 32), c.amount)
        coin_spend_0 = make_spend(coin_0, cs.puzzle_reveal, cs.solution)
        new_bundle = recursive_replace(spend_bundle, "coin_spends", [coin_spend_0] + spend_bundle.coin_spends[1:])
        assert spend_bundle is not None
        res = await full_node_1.full_node.add_transaction(new_bundle, new_bundle.name(), test=True)
        assert res == (MempoolInclusionStatus.FAILED, Err.INVALID_SPEND_BUNDLE)


coins = make_test_coins()


# This test makes sure we're properly sorting items by fee rate
@pytest.mark.parametrize(
    "items,expected",
    [
        # make sure fractions of fee-rate are ordered correctly (i.e. that
        # we don't use integer division)
        (
            [
                mk_item(coins[0:1], fee=110, cost=50),
                mk_item(coins[1:2], fee=100, cost=50),
                mk_item(coins[2:3], fee=105, cost=50),
            ],
            [coins[0], coins[2], coins[1]],
        ),
        # make sure insertion order is a tie-breaker for items with the same
        # fee-rate
        (
            [
                mk_item(coins[0:1], fee=100, cost=50),
                mk_item(coins[1:2], fee=100, cost=50),
                mk_item(coins[2:3], fee=100, cost=50),
            ],
            [coins[0], coins[1], coins[2]],
        ),
        # also for items that don't pay fees
        (
            [
                mk_item(coins[2:3], fee=0, cost=50),
                mk_item(coins[1:2], fee=0, cost=50),
                mk_item(coins[0:1], fee=0, cost=50),
            ],
            [coins[2], coins[1], coins[0]],
        ),
    ],
)
def test_items_by_feerate(items: List[MempoolItem], expected: List[Coin]) -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(11000000000))

    mempool_info = MempoolInfo(
        CLVMCost(uint64(11000000000 * 3)),
        FeeRate(uint64(1000000)),
        CLVMCost(uint64(11000000000)),
    )
    mempool = Mempool(mempool_info, fee_estimator)
    for i in items:
        mempool.add_to_pool(i)

    ordered_items = list(mempool.items_by_feerate())

    assert len(ordered_items) == len(expected)

    last_fpc: Optional[float] = None
    for mi, expected_coin in zip(ordered_items, expected):
        assert len(mi.spend_bundle.coin_spends) == 1
        assert mi.spend_bundle.coin_spends[0].coin == expected_coin
        assert last_fpc is None or last_fpc >= mi.fee_per_cost
        last_fpc = mi.fee_per_cost


def rand_hash() -> bytes32:
    rng = random.Random()
    ret = bytearray(32)
    for i in range(32):
        ret[i] = rng.getrandbits(8)
    return bytes32(ret)


def item_cost(cost: int, fee_rate: float) -> MempoolItem:
    fee = cost * fee_rate
    amount = uint64(fee + 100)
    coin = Coin(rand_hash(), rand_hash(), amount)
    return mk_item([coin], cost=cost, fee=int(cost * fee_rate))


@pytest.mark.parametrize(
    "items,add,expected",
    [
        # the max size is 100
        # we need to evict two items
        ([50, 25, 13, 12, 5], 10, [10, 50, 25, 13]),
        # we don't need to evict anything
        ([50, 25, 13], 10, [10, 50, 25, 13]),
        # we need to evict everything
        ([95, 5], 10, [10]),
        # we evict a single item
        ([75, 15, 9], 10, [10, 75, 15]),
    ],
)
def test_full_mempool(items: List[int], add: int, expected: List[int]) -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(11000000000))

    mempool_info = MempoolInfo(
        CLVMCost(uint64(100)),
        FeeRate(uint64(1000000)),
        CLVMCost(uint64(100)),
    )
    mempool = Mempool(mempool_info, fee_estimator)
    invariant_check_mempool(mempool)
    fee_rate: float = 3.0
    for i in items:
        mempool.add_to_pool(item_cost(i, fee_rate))
        fee_rate -= 0.1
        invariant_check_mempool(mempool)

    # now, add the item we're testing
    mempool.add_to_pool(item_cost(add, 3.1))
    invariant_check_mempool(mempool)

    ordered_items = list(mempool.items_by_feerate())

    assert len(ordered_items) == len(expected)

    for mi, expected_cost in zip(ordered_items, expected):
        assert mi.cost == expected_cost


@pytest.mark.parametrize("height", [True, False])
@pytest.mark.parametrize(
    "items,expected,increase_fee",
    [
        # the max size is 100
        # the max block size is 50
        # which is also the max size for expiring transactions
        # the increasing fee will order the transactions in the reverse
        # insertion order
        ([10, 11, 12, 13, 14], [14, 13, 12, 11], True),
        # decreasing fee rate will make the last one fail to be inserted
        ([10, 11, 12, 13, 14], [10, 11, 12, 13], False),
        # the last is big enough to evict all previous ones
        ([10, 11, 12, 13, 50], [50], True),
        # the last one will not evict any earlier ones, because the fee rate is
        # lower
        ([10, 11, 12, 13, 50], [10, 11, 12, 13], False),
    ],
)
def test_limit_expiring_transactions(height: bool, items: List[int], expected: List[int], increase_fee: bool) -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(11000000000))

    mempool_info = MempoolInfo(
        CLVMCost(uint64(100)),
        FeeRate(uint64(1000000)),
        CLVMCost(uint64(50)),
    )
    mempool = Mempool(mempool_info, fee_estimator)
    mempool.new_tx_block(uint32(10), uint64(100000))
    invariant_check_mempool(mempool)

    # fill the mempool with regular transactions (without expiration)
    fee_rate: float = 3.0
    for i in range(1, 20):
        mempool.add_to_pool(item_cost(i, fee_rate))
        fee_rate -= 0.1
        invariant_check_mempool(mempool)

    # now add the expiring transactions from the test case
    fee_rate = 2.7
    for cost in items:
        fee = cost * fee_rate
        amount = uint64(fee + 100)
        coin = Coin(rand_hash(), rand_hash(), amount)
        if height:
            ret = mempool.add_to_pool(mk_item([coin], cost=cost, fee=int(cost * fee_rate), assert_before_height=15))
        else:
            ret = mempool.add_to_pool(mk_item([coin], cost=cost, fee=int(cost * fee_rate), assert_before_seconds=10400))
        invariant_check_mempool(mempool)
        if increase_fee:
            fee_rate += 0.1
            assert ret.error is None
        else:
            fee_rate -= 0.1

    ordered_costs = [
        item.cost
        for item in mempool.items_by_feerate()
        if item.assert_before_height is not None or item.assert_before_seconds is not None
    ]

    assert ordered_costs == expected

    print("")
    for item in mempool.items_by_feerate():
        if item.assert_before_seconds is not None or item.assert_before_height is not None:
            ttl = "yes"
        else:
            ttl = "No"
        print(f"- cost: {item.cost} TTL: {ttl}")

    assert mempool.total_mempool_cost() > 90
    invariant_check_mempool(mempool)


@pytest.mark.parametrize(
    "items,coin_ids,expected",
    [
        # None of these spend those coins
        (
            [mk_item(coins[0:1]), mk_item(coins[1:2]), mk_item(coins[2:3])],
            [coins[3].name(), coins[4].name()],
            [],
        ),
        # One of these spends one of the coins
        (
            [mk_item(coins[0:1]), mk_item(coins[1:2]), mk_item(coins[2:3])],
            [coins[1].name(), coins[3].name()],
            [mk_item(coins[1:2])],
        ),
        # One of these spends one another spends two
        (
            [mk_item(coins[0:1]), mk_item(coins[1:3]), mk_item(coins[2:4]), mk_item(coins[3:4])],
            [coins[2].name(), coins[3].name()],
            [mk_item(coins[1:3]), mk_item(coins[2:4]), mk_item(coins[3:4])],
        ),
    ],
)
def test_get_items_by_coin_ids(items: List[MempoolItem], coin_ids: List[bytes32], expected: List[MempoolItem]) -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(11000000000))
    mempool_info = MempoolInfo(
        CLVMCost(uint64(11000000000 * 3)),
        FeeRate(uint64(1000000)),
        CLVMCost(uint64(11000000000)),
    )
    mempool = Mempool(mempool_info, fee_estimator)
    for i in items:
        mempool.add_to_pool(i)
        invariant_check_mempool(mempool)
    result = mempool.get_items_by_coin_ids(coin_ids)
    assert set(result) == set(expected)


@pytest.mark.anyio
async def test_aggregating_on_a_solution_then_a_more_cost_saving_one_appears() -> None:
    def always(_: bytes32) -> bool:
        return True

    async def get_unspent_lineage_info_for_puzzle_hash(_: bytes32) -> Optional[UnspentLineageInfo]:
        assert False  # pragma: no cover

    def make_test_spendbundle(coin: Coin, *, fee: int = 0, with_higher_cost: bool = False) -> SpendBundle:
        conditions = []
        actual_fee = fee
        if with_higher_cost:
            conditions.extend([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, i] for i in range(3)])
            actual_fee += 3
        conditions.append([ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, coin.amount - actual_fee])
        sb = spend_bundle_from_conditions(conditions, coin)
        return sb

    def agg_and_add_sb_returning_cost_info(mempool: Mempool, spend_bundles: List[SpendBundle]) -> uint64:
        sb = SpendBundle.aggregate(spend_bundles)
        mi = mempool_item_from_spendbundle(sb)
        mempool.add_to_pool(mi)
        invariant_check_mempool(mempool)
        saved_cost = run_for_cost(
            sb.coin_spends[0].puzzle_reveal, sb.coin_spends[0].solution, len(mi.additions), mi.cost
        )
        return saved_cost

    fee_estimator = create_bitcoin_fee_estimator(uint64(11000000000))
    mempool_info = MempoolInfo(
        CLVMCost(uint64(11000000000 * 3)),
        FeeRate(uint64(1000000)),
        CLVMCost(uint64(11000000000)),
    )
    mempool = Mempool(mempool_info, fee_estimator)
    coins = [
        Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, uint64(amount)) for amount in range(2000000000, 2000000020, 2)
    ]
    # Create a ~10 FPC item that spends the eligible coin[0]
    sb_A = make_test_spendbundle(coins[0])
    highest_fee = 58282830
    sb_high_rate = make_test_spendbundle(coins[1], fee=highest_fee)
    agg_and_add_sb_returning_cost_info(mempool, [sb_A, sb_high_rate])
    invariant_check_mempool(mempool)
    # Create a ~2 FPC item that spends the eligible coin using the same solution A
    sb_low_rate = make_test_spendbundle(coins[2], fee=highest_fee // 5)
    saved_cost_on_solution_A = agg_and_add_sb_returning_cost_info(mempool, [sb_A, sb_low_rate])
    invariant_check_mempool(mempool)
    result = await mempool.create_bundle_from_mempool_items(
        always, get_unspent_lineage_info_for_puzzle_hash, test_constants, uint32(0)
    )
    assert result is not None
    agg, _ = result
    # Make sure both items would be processed
    assert [c.coin for c in agg.coin_spends] == [coins[0], coins[1], coins[2]]
    # Now let's add 3 x ~3 FPC items that spend the eligible coin differently
    # (solution B). It creates a higher (saved) cost than solution A
    sb_B = make_test_spendbundle(coins[0], with_higher_cost=True)
    for i in range(3, 6):
        # We're picking this fee to get a ~3 FPC, and get picked after sb_A1
        # (which has ~10 FPC) but before sb_A2 (which has ~2 FPC)
        sb_mid_rate = make_test_spendbundle(coins[i], fee=38004852 - i)
        saved_cost_on_solution_B = agg_and_add_sb_returning_cost_info(mempool, [sb_B, sb_mid_rate])
        invariant_check_mempool(mempool)
    # We'd save more cost if we went with solution B instead of A
    assert saved_cost_on_solution_B > saved_cost_on_solution_A
    # If we process everything now, the 3 x ~3 FPC items get skipped because
    # sb_A1 gets picked before them (~10 FPC), so from then on only sb_A2 (~2 FPC)
    # would get picked
    result = await mempool.create_bundle_from_mempool_items(
        always, get_unspent_lineage_info_for_puzzle_hash, test_constants, uint32(0)
    )
    assert result is not None
    agg, _ = result
    # The 3 items got skipped here
    # We ran with solution A and missed bigger savings on solution B
    assert mempool.size() == 5
    assert [c.coin for c in agg.coin_spends] == [coins[0], coins[1], coins[2]]
    invariant_check_mempool(mempool)


def test_get_puzzle_and_solution_for_coin_failure() -> None:
    with pytest.raises(
        ValueError, match=f"Failed to get puzzle and solution for coin {TEST_COIN}, error: \\('coin not found', '80'\\)"
    ):
        get_puzzle_and_solution_for_coin(BlockGenerator(SerializedProgram.to(None), []), TEST_COIN, 0, test_constants)
