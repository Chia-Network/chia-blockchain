import asyncio
import logging
from time import time
from typing import Dict, List

import pytest

from chia.full_node.mempool import Mempool
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
from chia.util.errors import Err
from chia.util.ints import uint64

from tests.connection_utils import connect_and_get_peer
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import bt, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import Program, INFINITE_COST

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
        await full_node_1.respond_transaction(tx1, peer)

        spend_bundle2 = generate_test_spend_bundle(
            list(blocks[-1].get_included_reward_coins())[0],
            new_puzzle_hash=BURN_PUZZLE_HASH_2,
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle2)
        await full_node_1.respond_transaction(tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 == spend_bundle1
        assert sb2 is None

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
        coin3 = next(coins)

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

    @pytest.mark.asyncio
    async def test_invalid_block_index(self, two_nodes):
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

        cvp = ConditionWithArgs(
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            [uint64(start_height + 5).to_bytes(4, "big")],
        )
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_index(self, two_nodes):
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

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [uint64(1).to_bytes(4, "big")])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_block_age(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [uint64(5).to_bytes(4, "big")])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_age(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            4,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 4)

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [uint64(1).to_bytes(4, "big")])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-2].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_my_id(self, two_nodes):
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
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin.name()])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_my_id(self, two_nodes):
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

        coin = list(blocks[-1].get_included_reward_coins())[0]
        coin_2 = list(blocks[-2].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin_2.name()])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_assert_time_exceeds(self, two_nodes):
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

        time_now = uint64(int(time()))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [time_now.to_bytes(8, "big")])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_assert_time_relative_exceeds(self, two_nodes):
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

        time_relative = uint64(3)

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [time_relative.to_bytes(8, "big")])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)
        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None

        for i in range(0, 4):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_coin_announcement_consumed(self, two_nodes):
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

        announce = Announcement(coin_2.name(), bytes("test", "utf-8"))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

        dic = {cvp.opcode: [cvp]}

        cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [bytes("test", "utf-8")])
        dic2 = {cvp.opcode: [cvp2]}
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(bundle)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle

    @pytest.mark.asyncio
    async def test_coin_announcement_too_big(self, two_nodes):
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

        announce = Announcement(coin_2.name(), bytes([1] * 10000))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

        dic = {cvp.opcode: [cvp]}

        cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [bytes("test", "utf-8")])
        dic2 = {cvp.opcode: [cvp2]}
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(bundle)
        await full_node_1.respond_transaction(tx1, peer)

        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None

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

        announce = Announcement(coin_2.name(), bytes("test", "utf-8"))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

        dic = {cvp.opcode: [cvp]}
        # Wrong message
        cvp2 = ConditionWithArgs(
            ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
            [bytes("wrong test", "utf-8")],
        )
        dic2 = {cvp.opcode: [cvp2]}
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_invalid_coin_announcement_rejected_two(self, two_nodes):
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

        announce = Announcement(coin_1.name(), bytes("test", "utf-8"))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

        dic = {cvp.opcode: [cvp]}

        cvp2 = ConditionWithArgs(
            ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
            [bytes("test", "utf-8")],
        )
        dic2 = {cvp.opcode: [cvp2]}
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        # coin 2 is making the announcement, right message wrong coin
        spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_correct_puzzle_announcement(self, two_nodes):
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

        announce = Announcement(coin_2.puzzle_hash, bytes(0x80))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

        dic = {cvp.opcode: [cvp]}

        cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [bytes(0x80)])
        dic2 = {cvp.opcode: [cvp2]}
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(bundle)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement_rejected(self, two_nodes):
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

        announce = Announcement(coin_2.puzzle_hash, bytes("test", "utf-8"))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

        dic = {cvp.opcode: [cvp]}

        cvp2 = ConditionWithArgs(
            ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
            [bytes("wrong test", "utf-8")],
        )
        dic2 = {cvp.opcode: [cvp2]}
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement_rejected_two(self, two_nodes):
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

        announce = Announcement(coin_2.puzzle_hash, bytes("test", "utf-8"))

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

        dic = {cvp.opcode: [cvp]}
        # Wrong type of Create_announcement
        cvp2 = ConditionWithArgs(
            ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
            [bytes("test", "utf-8")],
        )
        dic2 = {cvp.opcode: [cvp2]}
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        spend_bundle2 = generate_test_spend_bundle(coin_2, dic2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_assert_fee_condition(self, two_nodes):
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

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic, uint64(10))

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is not None

    @pytest.mark.asyncio
    async def test_assert_fee_condition_negative_fee(self, two_nodes):
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

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic, uint64(10))

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        await full_node_1.respond_transaction(tx1, peer)
        assert full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name()) is None

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle1
        )
        assert (await full_node_1.full_node.blockchain.receive_block(blocks[-1]))[1] == Err.RESERVE_FEE_CONDITION_FAILED

    @pytest.mark.asyncio
    async def test_assert_fee_condition_wrong_fee(self, two_nodes):
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

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic, uint64(9))

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is None

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

        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is None

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

        await full_node_1.respond_transaction(tx, peer)

        sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle_combined.name())
        assert sb is None

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
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin.parent_coin_info])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_my_parent(self, two_nodes):
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

        coin = list(blocks[-1].get_included_reward_coins())[0]
        coin_2 = list(blocks[-2].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin_2.parent_coin_info])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_my_puzhash(self, two_nodes):
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
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [coin.puzzle_hash])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_my_puzhash(self, two_nodes):
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

        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [Program.to([]).get_tree_hash()])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_my_amount(self, two_nodes):
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
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [coin.amount])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_my_amount(self, two_nodes):
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

        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [1000])
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
