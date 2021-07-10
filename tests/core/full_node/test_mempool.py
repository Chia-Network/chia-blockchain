import asyncio
import logging

from typing import Dict, List, Optional, Tuple, Callable

import pytest
from clvm import SExp
from clvm.EvalError import EvalError

import chia.server.ws_connection as ws

from chia.full_node.mempool import Mempool
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_solution import CoinSolution
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle import SpendBundle
from chia.util.clvm import int_to_bytes
from chia.util.condition_tools import conditions_for_solution
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint64
from chia.util.hash import std_hash
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.api_decorators import api_request, peer_required, bytes_required
from chia.full_node.mempool_check_conditions import parse_condition_args

from tests.connection_utils import connect_and_get_peer
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import bt, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.consensus.condition_costs import ConditionCost

BURN_PUZZLE_HASH = b"0" * 32
BURN_PUZZLE_HASH_2 = b"1" * 32

WALLET_A = bt.get_pool_wallet_tool()

log = logging.getLogger(__name__)


def generate_test_spend_bundle(
    coin: Coin,
    condition_dic: Dict[ConditionOpcode, List[ConditionWithArgs]] = None,
    fee: uint64 = uint64(0),
    amount: uint64 = uint64(1000),
    new_puzzle_hash=BURN_PUZZLE_HASH,
) -> SpendBundle:
    if condition_dic is None:
        condition_dic = {}
    transaction = WALLET_A.generate_signed_transaction(amount, new_puzzle_hash, coin, condition_dic, fee)
    assert transaction is not None
    return transaction


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def two_nodes():
    async_gen = setup_simulators_and_wallets(2, 1, {})
    nodes, _ = await async_gen.__anext__()
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    yield full_node_1, full_node_2, server_1, server_2

    async for _ in async_gen:
        yield _


class TestMempool:
    @pytest.mark.asyncio
    async def test_basic_mempool(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, _, server_1, _ = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, blocks[-1].height)

        max_mempool_cost = 40000000 * 5
        mempool = Mempool(max_mempool_cost)
        assert mempool.get_min_fee_rate(104000) == 0

        with pytest.raises(ValueError):
            mempool.get_min_fee_rate(max_mempool_cost + 1)

        spend_bundle = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0])
        assert spend_bundle is not None


@peer_required
@api_request
@bytes_required
async def respond_transaction(
    node: FullNodeAPI,
    tx: full_node_protocol.RespondTransaction,
    peer: ws.WSChiaConnection,
    tx_bytes: bytes = b"",
    test: bool = False,
) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
    """
    Receives a full transaction from peer.
    If tx is added to mempool, send tx_id to others. (new_transaction)
    """
    assert tx_bytes != b""
    spend_name = std_hash(tx_bytes)
    if spend_name in node.full_node.full_node_store.pending_tx_request:
        node.full_node.full_node_store.pending_tx_request.pop(spend_name)
    if spend_name in node.full_node.full_node_store.peers_with_tx:
        node.full_node.full_node_store.peers_with_tx.pop(spend_name)
    return await node.full_node.respond_transaction(tx.transaction, spend_name, peer, test)


class TestMempoolManager:
    @pytest.mark.asyncio
    async def test_basic_mempool_manager(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            5,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_2, blocks[-1].height)

        spend_bundle = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0])
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        res = await full_node_1.respond_transaction(tx, peer)
        log.info(f"Res {res}")

        await time_out_assert(
            10,
            full_node_1.full_node.mempool_manager.get_spendbundle,
            spend_bundle,
            spend_bundle.name(),
        )

    @pytest.mark.asyncio
    async def test_double_spend(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0])

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        status, err = await respond_transaction(full_node_1, tx1, peer)
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

        spend_bundle2 = generate_test_spend_bundle(
            list(blocks[-1].get_included_reward_coins())[0],
            new_puzzle_hash=BURN_PUZZLE_HASH_2,
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle2)
        status, err = await respond_transaction(full_node_1, tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 == spend_bundle1
        assert sb2 is None
        assert status == MempoolInclusionStatus.PENDING
        assert err == Err.MEMPOOL_CONFLICT

    async def send_sb(self, node, peer, sb):
        tx = full_node_protocol.RespondTransaction(sb)
        await node.respond_transaction(tx, peer)

    async def gen_and_send_sb(self, node, peer, *args, **kwargs):
        sb = generate_test_spend_bundle(*args, **kwargs)
        assert sb is not None

        await self.send_sb(node, peer, sb)
        return sb

    def assert_sb_in_pool(self, node, sb):
        assert sb == node.full_node.mempool_manager.get_spendbundle(sb.name())

    def assert_sb_not_in_pool(self, node, sb):
        assert node.full_node.mempool_manager.get_spendbundle(sb.name()) is None

    @pytest.mark.asyncio
    async def test_double_spend_with_higher_fee(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coins = iter(blocks[-1].get_included_reward_coins())
        coin1, coin2 = next(coins), next(coins)
        coins = iter(blocks[-2].get_included_reward_coins())
        coin3, coin4 = next(coins), next(coins)

        sb1_1 = await self.gen_and_send_sb(full_node_1, peer, coin1)
        sb1_2 = await self.gen_and_send_sb(full_node_1, peer, coin1, fee=uint64(1))

        # Fee increase is insufficient, the old spendbundle must stay
        self.assert_sb_in_pool(full_node_1, sb1_1)
        self.assert_sb_not_in_pool(full_node_1, sb1_2)

        min_fee_increase = full_node_1.full_node.mempool_manager.get_min_fee_increase()

        sb1_3 = await self.gen_and_send_sb(full_node_1, peer, coin1, fee=uint64(min_fee_increase))

        # Fee increase is sufficiently high, sb1_1 gets replaced with sb1_3
        self.assert_sb_not_in_pool(full_node_1, sb1_1)
        self.assert_sb_in_pool(full_node_1, sb1_3)

        sb2 = generate_test_spend_bundle(coin2, fee=uint64(min_fee_increase))
        sb12 = SpendBundle.aggregate((sb2, sb1_3))
        await self.send_sb(full_node_1, peer, sb12)

        # Aggregated spendbundle sb12 replaces sb1_3 since it spends a superset
        # of coins spent in sb1_3
        self.assert_sb_in_pool(full_node_1, sb12)
        self.assert_sb_not_in_pool(full_node_1, sb1_3)

        sb3 = generate_test_spend_bundle(coin3, fee=uint64(min_fee_increase * 2))
        sb23 = SpendBundle.aggregate((sb2, sb3))
        await self.send_sb(full_node_1, peer, sb23)

        # sb23 must not replace existing sb12 as the former does not spend all
        # coins that are spent in the latter (specifically, coin1)
        self.assert_sb_in_pool(full_node_1, sb12)
        self.assert_sb_not_in_pool(full_node_1, sb23)

        await self.send_sb(full_node_1, peer, sb3)
        # Adding non-conflicting sb3 should succeed
        self.assert_sb_in_pool(full_node_1, sb3)

        sb4_1 = generate_test_spend_bundle(coin4, fee=uint64(min_fee_increase))
        sb1234_1 = SpendBundle.aggregate((sb12, sb3, sb4_1))
        await self.send_sb(full_node_1, peer, sb1234_1)
        # sb1234_1 should not be in pool as it decreases total fees per cost
        self.assert_sb_not_in_pool(full_node_1, sb1234_1)

        sb4_2 = generate_test_spend_bundle(coin4, fee=uint64(min_fee_increase * 2))
        sb1234_2 = SpendBundle.aggregate((sb12, sb3, sb4_2))
        await self.send_sb(full_node_1, peer, sb1234_2)
        # sb1234_2 has a higher fee per cost than its conflicts and should get
        # into mempool
        self.assert_sb_in_pool(full_node_1, sb1234_2)
        self.assert_sb_not_in_pool(full_node_1, sb12)
        self.assert_sb_not_in_pool(full_node_1, sb3)

    async def condition_tester(
        self,
        two_nodes,
        dic: Dict[ConditionOpcode, List[ConditionWithArgs]],
        fee: int = 0,
        num_blocks: int = 3,
        coin: Optional[Coin] = None,
    ):
        reward_ph = WALLET_A.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            num_blocks,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + num_blocks)

        spend_bundle1 = generate_test_spend_bundle(
            coin or list(blocks[-num_blocks + 2].get_included_reward_coins())[0], dic, uint64(fee)
        )

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx1, peer)
        return blocks, spend_bundle1, peer, status, err

    @pytest.mark.asyncio
    async def condition_tester2(self, two_nodes, test_fun: Callable[[Coin, Coin], SpendBundle]):
        reward_ph = WALLET_A.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height if len(blocks) > 0 else -1
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin_1 = list(blocks[-2].get_included_reward_coins())[0]
        coin_2 = list(blocks[-1].get_included_reward_coins())[0]

        bundle = test_fun(coin_1, coin_2)

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(bundle)
        status, err = await respond_transaction(full_node_1, tx1, peer)

        return blocks, bundle, status, err

    @pytest.mark.asyncio
    async def test_invalid_block_index(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        cvp = ConditionWithArgs(
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            [int_to_bytes(start_height + 5)],
        )
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.PENDING
        assert err == Err.ASSERT_HEIGHT_ABSOLUTE_FAILED

    @pytest.mark.asyncio
    async def test_block_index_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_correct_block_index(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(1)])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_block_index_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(1), b"garbage"])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_negative_block_index(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(-1)])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_invalid_block_age(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(5)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.PENDING
        assert err == Err.ASSERT_HEIGHT_RELATIVE_FAILED

    @pytest.mark.asyncio
    async def test_block_age_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_correct_block_age(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, num_blocks=4)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_block_age_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(1), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, num_blocks=4)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_negative_block_age(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, num_blocks=4)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_correct_my_id(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin.name()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_my_id_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin.name(), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_invalid_my_id(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        coin_2 = list(blocks[-2].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin_2.name()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_MY_COIN_ID_FAILED

    @pytest.mark.asyncio
    async def test_my_id_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_assert_time_exceeds(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # 5 seconds should be before the next block
        time_now = full_node_1.full_node.blockchain.get_peak().timestamp + 5

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_assert_time_fail(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_now = full_node_1.full_node.blockchain.get_peak().timestamp + 1000

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_SECONDS_ABSOLUTE_FAILED

    @pytest.mark.asyncio
    async def test_assert_time_negative(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_now = -1

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_assert_time_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_assert_time_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_now = full_node_1.full_node.blockchain.get_peak().timestamp + 5

        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_assert_time_relative_exceeds(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_relative = 3

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_SECONDS_RELATIVE_FAILED

        for i in range(0, 4):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_assert_time_relative_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_relative = 0

        # garbage at the end of the arguments is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_assert_time_relative_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_assert_time_relative_negative(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_relative = -3

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_correct_coin_announcement_consumed(self, two_nodes):
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = Announcement(coin_2.name(), b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_coin_announcement_garbage(self, two_nodes):
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = Announcement(coin_2.name(), b"test")
            # garbage at the end is ignored
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name(), b"garbage"])
            dic = {cvp.opcode: [cvp]}

            # garbage at the end is ignored
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test", b"garbage"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_coin_announcement_missing_arg(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            # missing arg here
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [])
            dic = {cvp.opcode: [cvp]}
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_coin_announcement_missing_arg2(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.name(), b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp]}
            # missing arg here
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_coin_announcement_too_big(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.name(), bytes([1] * 10000))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=bundle
        )
        try:
            await full_node_1.full_node.blockchain.receive_block(blocks[-1])
            assert False
        except AssertionError:
            pass

    @pytest.mark.asyncio
    async def test_invalid_coin_announcement_rejected(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.name(), b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}
            # Wrong message
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
                [b"wrong test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    @pytest.mark.asyncio
    async def test_invalid_coin_announcement_rejected_two(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_1.name(), b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
                [b"test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            # coin 2 is making the announcement, right message wrong coin
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    @pytest.mark.asyncio
    async def test_correct_puzzle_announcement(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, bytes(0x80))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [bytes(0x80)])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_puzzle_announcement_garbage(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, bytes(0x80))

            # garbage at the end is ignored
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name(), b"garbage"])
            dic = {cvp.opcode: [cvp]}
            # garbage at the end is ignored
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [bytes(0x80), b"garbage"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_puzzle_announcement_missing_arg(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            # missing arg here
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [])
            dic = {cvp.opcode: [cvp]}
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [b"test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_puzzle_announcement_missing_arg2(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp]}
            # missing arg here
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement_rejected(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, bytes("test", "utf-8"))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [b"wrong test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement_rejected_two(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}
            # Wrong type of Create_announcement
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
                [b"test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(two_nodes, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    @pytest.mark.asyncio
    async def test_assert_fee_condition(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, fee=10)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is not None
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_assert_fee_condition_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # garbage at the end of the arguments is ignored
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, fee=10)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is not None
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_assert_fee_condition_missing_arg(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, fee=10)
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_assert_fee_condition_negative_fee(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, fee=10)
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle1
        )
        assert full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name()) is None
        assert (await full_node_1.full_node.blockchain.receive_block(blocks[-1]))[1] == Err.RESERVE_FEE_CONDITION_FAILED

    @pytest.mark.asyncio
    async def test_assert_fee_condition_fee_too_large(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(2 ** 64)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, fee=10)
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle1
        )
        assert full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name()) is None
        assert (await full_node_1.full_node.blockchain.receive_block(blocks[-1]))[1] == Err.RESERVE_FEE_CONDITION_FAILED

    @pytest.mark.asyncio
    async def test_assert_fee_condition_wrong_fee(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, fee=9)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.RESERVE_FEE_CONDITION_FAILED

    @pytest.mark.asyncio
    async def test_stealing_fee(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            5,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 5)

        receiver_puzzlehash = BURN_PUZZLE_HASH

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}

        fee = 9

        coin_1 = list(blocks[-2].get_included_reward_coins())[0]
        coin_2 = None
        for coin in list(blocks[-1].get_included_reward_coins()):
            if coin.amount == coin_1.amount:
                coin_2 = coin
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic, uint64(fee))

        steal_fee_spendbundle = WALLET_A.generate_signed_transaction(
            coin_1.amount + fee - 4, receiver_puzzlehash, coin_2
        )

        assert spend_bundle1 is not None
        assert steal_fee_spendbundle is not None

        combined = SpendBundle.aggregate([spend_bundle1, steal_fee_spendbundle])

        assert combined.fees() == 4

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.RESERVE_FEE_CONDITION_FAILED

    @pytest.mark.asyncio
    async def test_double_spend_same_bundle(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)
        coin = list(blocks[-1].get_included_reward_coins())[0]
        spend_bundle1 = generate_test_spend_bundle(coin)

        assert spend_bundle1 is not None

        spend_bundle2 = generate_test_spend_bundle(
            coin,
            new_puzzle_hash=BURN_PUZZLE_HASH_2,
        )

        assert spend_bundle2 is not None

        spend_bundle_combined = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle_combined)

        status, err = await respond_transaction(full_node_1, tx, peer)

        sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle_combined.name())
        assert sb is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.DOUBLE_SPEND

    @pytest.mark.asyncio
    async def test_agg_sig_condition(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
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
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        # this code has been changed to use generate_test_spend_bundle
        # not quite sure why all the gymnastics are being performed

        coin = list(blocks[-1].get_included_reward_coins())[0]
        spend_bundle_0 = generate_test_spend_bundle(coin)
        unsigned: List[CoinSolution] = spend_bundle_0.coin_solutions

        assert len(unsigned) == 1
        coin_solution: CoinSolution = unsigned[0]

        err, con, cost = conditions_for_solution(coin_solution.puzzle_reveal, coin_solution.solution, INFINITE_COST)
        assert con is not None

        # TODO(straya): fix this test
        # puzzle, solution = list(coin_solution.solution.as_iter())
        # conditions_dict = conditions_by_opcode(con)

        # pkm_pairs = pkm_pairs_for_conditions_dict(conditions_dict, coin_solution.coin.name())
        # assert len(pkm_pairs) == 1
        #
        # assert pkm_pairs[0][1] == solution.rest().first().get_tree_hash() + coin_solution.coin.name()
        #
        # spend_bundle = WALLET_A.sign_transaction(unsigned)
        # assert spend_bundle is not None
        #
        # tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        # await full_node_1.respond_transaction(tx, peer)
        #
        # sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle.name())
        # assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_correct_my_parent(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin.parent_coin_info])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_my_parent_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        # garbage at the end of the arguments list is allowed but stripped
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin.parent_coin_info, b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_my_parent_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_invalid_my_parent(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        coin_2 = list(blocks[-2].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin_2.parent_coin_info])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_MY_PARENT_ID_FAILED

    @pytest.mark.asyncio
    async def test_correct_my_puzhash(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [coin.puzzle_hash])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_my_puzhash_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        # garbage at the end of the arguments list is allowed but stripped
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [coin.puzzle_hash, b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_my_puzhash_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_invalid_my_puzhash(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [Program.to([]).get_tree_hash()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_MY_PUZZLEHASH_FAILED

    @pytest.mark.asyncio
    async def test_correct_my_amount(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(coin.amount)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_my_amount_garbage(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        coin = list(blocks[-1].get_included_reward_coins())[0]
        # garbage at the end of the arguments list is allowed but stripped
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(coin.amount), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

    @pytest.mark.asyncio
    async def test_my_amount_missing_arg(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.GENERATOR_RUNTIME_ERROR

    @pytest.mark.asyncio
    async def test_invalid_my_amount(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(1000)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_MY_AMOUNT_FAILED

    @pytest.mark.asyncio
    async def test_negative_my_amount(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_MY_AMOUNT_FAILED

    @pytest.mark.asyncio
    async def test_my_amount_too_large(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(2 ** 64)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.ASSERT_MY_AMOUNT_FAILED

    @pytest.mark.asyncio
    async def test_unknown_condition(self, two_nodes):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.UNKNOWN, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(two_nodes, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED
        assert err == Err.INVALID_CONDITION


class TestConditionParser:
    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_agg_sig(self, safe_mode: bool):

        valid_pubkey = b"b" * 48
        short_pubkey = b"b" * 47
        long_pubkey = b"b" * 49

        valid_message = b"a" * 1024
        long_message = b"a" * 1025
        empty_message = b""

        for condition_code in [ConditionOpcode.AGG_SIG_UNSAFE, ConditionOpcode.AGG_SIG_ME]:
            cost, args = parse_condition_args(SExp.to([valid_pubkey, valid_message]), condition_code, safe_mode)
            assert cost == ConditionCost.AGG_SIG.value
            assert args == [valid_pubkey, valid_message]

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([valid_pubkey, long_message]), condition_code, safe_mode)

            # empty messages are allowed
            cost, args = parse_condition_args(SExp.to([valid_pubkey, empty_message]), condition_code, safe_mode)
            assert cost == ConditionCost.AGG_SIG.value
            assert args == [valid_pubkey, empty_message]

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([short_pubkey, valid_message]), condition_code, safe_mode)

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([long_pubkey, valid_message]), condition_code, safe_mode)

            # missing message argument
            with pytest.raises(EvalError):
                cost, args = parse_condition_args(SExp.to([valid_pubkey]), condition_code, safe_mode)

            # missing all arguments
            with pytest.raises(EvalError):
                cost, args = parse_condition_args(SExp.to([]), condition_code, safe_mode)

            # garbage at the end of the arguments list is allowed but stripped
            cost, args = parse_condition_args(
                SExp.to([valid_pubkey, valid_message, b"garbage"]), condition_code, safe_mode
            )
            assert cost == ConditionCost.AGG_SIG.value
            assert args == [valid_pubkey, valid_message]

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_create_coin(self, safe_mode: bool):

        valid_hash = b"b" * 32
        short_hash = b"b" * 31
        long_hash = b"b" * 33

        valid_amount = int_to_bytes(1000000000)
        # this is greater than max coin amount
        large_amount = int_to_bytes(2 ** 64)
        leading_zeros_amount = bytes([0] * 100) + int_to_bytes(1000000000)
        negative_amount = int_to_bytes(-1000)
        # this ist still -1, but just with a lot of (redundant) 0xff bytes
        # prepended
        large_negative_amount = bytes([0xFF] * 100) + int_to_bytes(-1)

        cost, args = parse_condition_args(SExp.to([valid_hash, valid_amount]), ConditionOpcode.CREATE_COIN, safe_mode)
        assert cost == ConditionCost.CREATE_COIN.value
        assert args == [valid_hash, valid_amount]

        if safe_mode:
            # we don't allow over-long encoding in safe-mode
            with pytest.raises(ValidationError):
                parse_condition_args(
                    SExp.to([valid_hash, leading_zeros_amount]), ConditionOpcode.CREATE_COIN, safe_mode
                )
        else:
            cost, args = parse_condition_args(
                SExp.to([valid_hash, leading_zeros_amount]), ConditionOpcode.CREATE_COIN, safe_mode
            )
            assert cost == ConditionCost.CREATE_COIN.value
            # the amount will have its leading zeros stripped
            assert args == [valid_hash, valid_amount]

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(
                SExp.to([valid_hash, large_amount]), ConditionOpcode.CREATE_COIN, safe_mode
            )

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(
                SExp.to([short_hash, valid_amount]), ConditionOpcode.CREATE_COIN, safe_mode
            )

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(
                SExp.to([long_hash, valid_amount]), ConditionOpcode.CREATE_COIN, safe_mode
            )

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(
                SExp.to([valid_hash, negative_amount]), ConditionOpcode.CREATE_COIN, safe_mode
            )

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(
                SExp.to([valid_hash, large_negative_amount]), ConditionOpcode.CREATE_COIN, safe_mode
            )

        # missing amount
        with pytest.raises(EvalError):
            cost, args = parse_condition_args(SExp.to([valid_hash]), ConditionOpcode.CREATE_COIN, safe_mode)

        # missing everything
        with pytest.raises(EvalError):
            cost, args = parse_condition_args(SExp.to([]), ConditionOpcode.CREATE_COIN, safe_mode)

        # garbage at the end of the arguments list is allowed but stripped
        cost, args = parse_condition_args(
            SExp.to([valid_hash, valid_amount, b"garbage"]), ConditionOpcode.CREATE_COIN, safe_mode
        )
        assert cost == ConditionCost.CREATE_COIN.value
        assert args == [valid_hash, valid_amount]

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_seconds(self, safe_mode: bool):

        valid_timestamp = int_to_bytes(100)
        leading_zeros_timestamp = bytes([0] * 100) + int_to_bytes(100)
        negative_timestamp = int_to_bytes(-100)
        large_negative_timestamp = bytes([0xFF] * 100) + int_to_bytes(-1)

        for condition_code in [ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, ConditionOpcode.ASSERT_SECONDS_RELATIVE]:
            cost, args = parse_condition_args(SExp.to([valid_timestamp]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_timestamp]

            if safe_mode:
                # we don't allow over-long encodings in strict mode
                with pytest.raises(ValidationError):
                    parse_condition_args(SExp.to([leading_zeros_timestamp]), condition_code, safe_mode)
            else:
                cost, args = parse_condition_args(SExp.to([leading_zeros_timestamp]), condition_code, safe_mode)
                assert cost == 0
                assert args == [valid_timestamp]

            # a condition with a negative timestamp is always true
            cost, args = parse_condition_args(SExp.to([negative_timestamp]), condition_code, safe_mode)
            assert cost == 0
            assert args is None

            cost, args = parse_condition_args(SExp.to([large_negative_timestamp]), condition_code, safe_mode)
            assert cost == 0
            assert args is None

            # garbage at the end of the arguments list is allowed but stripped
            cost, args = parse_condition_args(SExp.to([valid_timestamp, b"garbage"]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_timestamp]

            # missing argument
            with pytest.raises(EvalError):
                cost, args = parse_condition_args(SExp.to([]), condition_code, safe_mode)

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_height(self, safe_mode: bool):

        valid_height = int_to_bytes(100)
        leading_zeros_height = bytes([0] * 100) + int_to_bytes(100)
        negative_height = int_to_bytes(-100)
        large_negative_height = bytes([0xFF] * 100) + int_to_bytes(-1)

        for condition_code in [ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, ConditionOpcode.ASSERT_HEIGHT_RELATIVE]:
            cost, args = parse_condition_args(SExp.to([valid_height]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_height]

            if safe_mode:
                with pytest.raises(ValidationError):
                    parse_condition_args(SExp.to([leading_zeros_height]), condition_code, safe_mode)
            else:
                cost, args = parse_condition_args(SExp.to([leading_zeros_height]), condition_code, safe_mode)
                assert cost == 0
                assert args == [valid_height]

            # a condition with a negative height is always true
            cost, args = parse_condition_args(SExp.to([negative_height]), condition_code, safe_mode)
            assert cost == 0
            assert args is None

            cost, args = parse_condition_args(SExp.to([large_negative_height]), condition_code, safe_mode)
            assert cost == 0
            assert args is None

            # garbage at the end of the arguments list is allowed but stripped
            cost, args = parse_condition_args(SExp.to([valid_height, b"garbage"]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_height]

            # missing argument
            with pytest.raises(EvalError):
                cost, args = parse_condition_args(SExp.to([]), condition_code, safe_mode)

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_coin_id(self, safe_mode: bool):

        valid_coin_id = b"a" * 32
        short_coin_id = b"a" * 31
        long_coin_id = b"a" * 33

        for condition_code in [ConditionOpcode.ASSERT_MY_COIN_ID, ConditionOpcode.ASSERT_MY_PARENT_ID]:
            cost, args = parse_condition_args(SExp.to([valid_coin_id]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_coin_id]

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([short_coin_id]), condition_code, safe_mode)

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([long_coin_id]), condition_code, safe_mode)

            # garbage at the end of the arguments list is allowed but stripped
            cost, args = parse_condition_args(SExp.to([valid_coin_id, b"garbage"]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_coin_id]

            with pytest.raises(EvalError):
                cost, args = parse_condition_args(SExp.to([]), condition_code, safe_mode)

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_fee(self, safe_mode: bool):

        valid_fee = int_to_bytes(100)
        leading_zeros_fee = bytes([0] * 100) + int_to_bytes(100)
        negative_fee = int_to_bytes(-100)
        large_negative_fee = bytes([0xFF] * 100) + int_to_bytes(-1)
        large_fee = int_to_bytes(2 ** 64)

        cost, args = parse_condition_args(SExp.to([valid_fee]), ConditionOpcode.RESERVE_FEE, safe_mode)
        assert cost == 0
        assert args == [valid_fee]

        if safe_mode:
            with pytest.raises(ValidationError):
                parse_condition_args(SExp.to([leading_zeros_fee]), ConditionOpcode.RESERVE_FEE, safe_mode)
        else:
            cost, args = parse_condition_args(SExp.to([leading_zeros_fee]), ConditionOpcode.RESERVE_FEE, safe_mode)
            assert cost == 0
            assert args == [valid_fee]

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(SExp.to([negative_fee]), ConditionOpcode.RESERVE_FEE, safe_mode)

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(SExp.to([large_fee]), ConditionOpcode.RESERVE_FEE, safe_mode)

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(SExp.to([large_negative_fee]), ConditionOpcode.RESERVE_FEE, safe_mode)

        # garbage at the end of the arguments list is allowed but stripped
        cost, args = parse_condition_args(SExp.to([valid_fee, b"garbage"]), ConditionOpcode.RESERVE_FEE, safe_mode)
        assert cost == 0
        assert args == [valid_fee]

        # missing argument
        with pytest.raises(EvalError):
            cost, args = parse_condition_args(SExp.to([]), ConditionOpcode.RESERVE_FEE, safe_mode)

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_create_announcement(self, safe_mode: bool):

        valid_msg = b"a" * 1024
        long_msg = b"a" * 1025
        empty_msg = b""

        for condition_code in [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]:
            cost, args = parse_condition_args(SExp.to([valid_msg]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_msg]

            cost, args = parse_condition_args(SExp.to([empty_msg]), condition_code, safe_mode)
            assert cost == 0
            assert args == [empty_msg]

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([long_msg]), condition_code, safe_mode)

            # missing argument
            with pytest.raises(EvalError):
                cost, args = parse_condition_args(SExp.to([]), condition_code, safe_mode)

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_assert_announcement(self, safe_mode: bool):

        valid_hash = b"b" * 32
        short_hash = b"b" * 31
        long_hash = b"b" * 33

        for condition_code in [
            ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
            ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
            ConditionOpcode.ASSERT_MY_PUZZLEHASH,
        ]:
            cost, args = parse_condition_args(SExp.to([valid_hash]), condition_code, safe_mode)
            assert cost == 0
            assert args == [valid_hash]

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([short_hash]), condition_code, safe_mode)

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([long_hash]), condition_code, safe_mode)

            # missing argument
            with pytest.raises(EvalError):
                cost, args = parse_condition_args(SExp.to([]), condition_code, safe_mode)

    @pytest.mark.parametrize("safe_mode", [True, False])
    def test_parse_condition_my_amount(self, safe_mode: bool):

        valid_amount = int_to_bytes(100)
        leading_zeros_amount = bytes([0] * 100) + int_to_bytes(100)
        negative_amount = int_to_bytes(-100)
        large_negative_amount = bytes([0xFF] * 100) + int_to_bytes(-1)
        large_amount = int_to_bytes(2 ** 64)

        cost, args = parse_condition_args(SExp.to([valid_amount]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode)
        assert cost == 0
        assert args == [valid_amount]

        if safe_mode:
            with pytest.raises(ValidationError):
                parse_condition_args(SExp.to([leading_zeros_amount]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode)
        else:
            cost, args = parse_condition_args(
                SExp.to([leading_zeros_amount]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode
            )
            assert cost == 0
            assert args == [valid_amount]

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(SExp.to([negative_amount]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode)

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(SExp.to([large_amount]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode)

        with pytest.raises(ValidationError):
            cost, args = parse_condition_args(
                SExp.to([large_negative_amount]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode
            )

        # garbage at the end of the arguments list is allowed but stripped
        cost, args = parse_condition_args(
            SExp.to([valid_amount, b"garbage"]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode
        )
        assert cost == 0
        assert args == [valid_amount]

        # missing argument
        with pytest.raises(EvalError):
            cost, args = parse_condition_args(SExp.to([]), ConditionOpcode.ASSERT_MY_AMOUNT, safe_mode)

    def test_parse_unknown_condition(self):

        for opcode in [129, 0, 1, 1000, 74]:
            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([b"test"]), opcode, False)

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([b"foo", b"bar"]), opcode, False)

            with pytest.raises(ValidationError):
                cost, args = parse_condition_args(SExp.to([]), opcode, False)
