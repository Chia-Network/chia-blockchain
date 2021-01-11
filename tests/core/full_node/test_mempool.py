import asyncio
from time import time
from typing import Dict, List

import pytest

from src.protocols import full_node_protocol
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.spend_bundle import SpendBundle
from src.util.condition_tools import conditions_for_solution
from src.util.clvm import int_to_bytes
from src.util.ints import uint64
from tests.core.full_node.test_full_node import connect_and_get_peer, node_height_at_least
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.time_out_assert import time_out_assert

BURN_PUZZLE_HASH = b"0" * 32
BURN_PUZZLE_HASH_2 = b"1" * 32

WALLET_A = bt.get_pool_wallet_tool()


def generate_test_spend_bundle(
    coin: Coin,
    condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]] = None,
    fee: int = 0,
    amount: int = 1000,
    newpuzzlehash=BURN_PUZZLE_HASH,
) -> SpendBundle:
    if condition_dic is None:
        condition_dic = {}
    transaction = WALLET_A.generate_signed_transaction(amount, newpuzzlehash, coin, condition_dic, fee)
    assert transaction is not None
    return transaction


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestMempool:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        constants = test_constants.replace()
        async for _ in setup_two_nodes(constants):
            yield _

    @pytest.mark.asyncio
    async def test_basic_mempool(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_2, 2)

        spend_bundle = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0])
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        await full_node_1.respond_transaction(tx, peer)

        await time_out_assert(
            10,
            full_node_1.full_node.mempool_manager.get_spendbundle,
            spend_bundle,
            spend_bundle.name(),
        )

    @pytest.mark.asyncio
    async def test_double_spend(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0])

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        spend_bundle2 = generate_test_spend_bundle(
            list(blocks[-1].get_included_reward_coins())[0],
            newpuzzlehash=BURN_PUZZLE_HASH_2,
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle2)
        await full_node_1.respond_transaction(tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 == spend_bundle1
        assert sb2 is None

    @pytest.mark.asyncio
    async def test_double_spend_with_higher_fee(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0])
        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        await full_node_1.respond_transaction(tx1, peer)

        spend_bundle2 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], fee=1)

        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle2)

        await full_node_1.respond_transaction(tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 is None
        assert sb2 == spend_bundle2

    @pytest.mark.asyncio
    async def test_invalid_block_index(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS,
            uint64(4).to_bytes(4, "big"),
            None,
        )
        dic = {ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_index(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS,
            uint64(1).to_bytes(4, "big"),
            None,
        )
        dic = {ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS: [cvp]}

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
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        cvp = ConditionVarPair(ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, uint64(5).to_bytes(4, "big"), None)
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
        blocks = bt.get_consecutive_blocks(
            4,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 3)

        cvp = ConditionVarPair(ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, uint64(1).to_bytes(4, "big"), None)
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
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        coin = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionVarPair(ConditionOpcode.ASSERT_MY_COIN_ID, coin.name(), None)
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
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        coin = list(blocks[-1].get_included_reward_coins())[0]
        coin_2 = list(blocks[-2].get_included_reward_coins())[0]
        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID,
            coin_2.name(),
            None,
        )
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
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        time_now = uint64(int(time() * 1000))

        cvp = ConditionVarPair(ConditionOpcode.ASSERT_TIME_EXCEEDS, time_now.to_bytes(8, "big"), None)
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_assert_time_exceeds_both_cases(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        time_now = uint64(int(time() * 1000))
        time_now_plus_3 = time_now + 3000

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS,
            time_now_plus_3.to_bytes(8, "big"),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        # Sleep so that 3 sec passes
        await asyncio.sleep(3)

        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_coin_consumed(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            4,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 3)

        coin_1 = list(blocks[-2].get_included_reward_coins())[0]
        coin_2 = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED,
            coin_2.name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        spend_bundle2 = generate_test_spend_bundle(coin_2)

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(bundle)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle

    @pytest.mark.asyncio
    async def test_invalid_coin_consumed(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            4,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 3)

        for b in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(b))

        coin_1 = list(blocks[-2].get_included_reward_coins())[0]
        coin_2 = list(blocks[-1].get_included_reward_coins())[0]
        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED,
            coin_2.name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(coin_1, dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_assert_fee_condition(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_FEE,
            int_to_bytes(10),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic, 10)

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is not None

    @pytest.mark.asyncio
    async def test_assert_fee_condition_wrong_fee(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_FEE,
            int_to_bytes(10),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(list(blocks[-1].get_included_reward_coins())[0], dic, 9)

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        await full_node_1.respond_transaction(tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_stealing_fee(self, two_nodes):
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            5,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 4)

        receiver_puzzlehash = BURN_PUZZLE_HASH

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_FEE,
            int_to_bytes(10),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        fee = 9

        coin_1 = list(blocks[-2].get_included_reward_coins())[0]
        coin_2 = None
        for coin in list(blocks[-1].get_included_reward_coins()):
            if coin.amount == coin_1.amount:
                coin_2 = coin
        spend_bundle1 = generate_test_spend_bundle(coin_1, dic, fee)

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
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)
        coin = list(blocks[-1].get_included_reward_coins())[0]
        spend_bundle1 = generate_test_spend_bundle(coin)

        assert spend_bundle1 is not None

        spend_bundle2 = generate_test_spend_bundle(
            coin,
            newpuzzlehash=BURN_PUZZLE_HASH_2,
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
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, 2)

        # this code has been changed to use generate_test_spend_bundle
        # not quite sure why all the gymnastics are being performed

        coin = list(blocks[-1].get_included_reward_coins())[0]
        spend_bundle_0 = generate_test_spend_bundle(coin)
        unsigned: List[CoinSolution] = spend_bundle_0.coin_solutions

        assert len(unsigned) == 1
        coin_solution = unsigned[0]

        err, con, cost = conditions_for_solution(coin_solution.solution)
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
