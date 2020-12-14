import asyncio
from time import time
from typing import Dict, List

import pytest

from src.server.outbound_message import OutboundMessage
from src.protocols import full_node_protocol
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.spend_bundle import SpendBundle
from src.util.condition_tools import (
    conditions_for_solution,
    conditions_by_opcode,
    pkm_pairs_for_conditions_dict,
)
from src.util.clvm import int_to_bytes
from src.util.ints import uint64
from tests.setup_nodes import setup_two_nodes, test_constants, bt

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
    transaction = WALLET_A.generate_signed_transaction(
        amount, newpuzzlehash, coin, condition_dic, fee
    )
    assert transaction is not None
    return transaction


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestMempool:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        constants = test_constants.replace(COINBASE_FREEZE_PERIOD=0)
        async for _ in setup_two_nodes(constants):
            yield _

    @pytest.fixture(scope="function")
    async def two_nodes_small_freeze(self):
        constants = test_constants.replace(COINBASE_FREEZE_PERIOD=30)
        async for _ in setup_two_nodes(constants):
            yield _

    @pytest.mark.asyncio
    async def test_basic_mempool(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_api, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_api.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        spend_bundle = generate_test_spend_bundle(block.get_coinbase())
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle)
        )
        await full_node_api.respond_transaction(tx, None)

        sb = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle.name()
        )
        assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_coinbase_freeze(self, two_nodes_small_freeze):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_api, full_node_2, server_1, server_2 = two_nodes_small_freeze

        block = blocks[1]
        await full_node_api.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        spend_bundle = generate_test_spend_bundle(block.get_coinbase())
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle)
        )

        await full_node_api.respond_transaction(tx, None)

        sb = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle.name()
        )
        assert sb is None

        blocks = bt.get_consecutive_blocks(test_constants, 30, [], 10, b"")

        for i in range(1, 31):
            await full_node_api.full_node._respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            )

        await full_node_api.respond_transaction(tx, None)

        sb = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle.name()
        )
        assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_double_spend(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_api, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_api.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase())

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_api.respond_transaction(tx1, None)

        spend_bundle2 = generate_test_spend_bundle(
            block.get_coinbase(),
            newpuzzlehash=BURN_PUZZLE_HASH_2,
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle2)
        )
        await full_node_api.respond_transaction(tx2, None)

        sb1 = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )
        sb2 = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle2.name()
        )

        assert sb1 == spend_bundle1
        assert sb2 is None

    @pytest.mark.asyncio
    async def test_double_spend_with_higher_fee(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_api, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_api.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase())
        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )

        await full_node_api.respond_transaction(tx1, None)

        spend_bundle2 = generate_test_spend_bundle(block.get_coinbase(), fee=1)

        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle2)
        )

        await full_node_api.respond_transaction(tx2, None)

        sb1 = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )
        sb2 = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle2.name()
        )

        assert sb1 is None
        assert sb2 == spend_bundle2

    @pytest.mark.asyncio
    async def test_invalid_block_index(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_api, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_api.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS,
            uint64(2).to_bytes(4, "big"),
            None,
        )
        dic = {ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_api.respond_transaction(tx1, None)

        sb1 = full_node_api.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_index(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_1.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS,
            uint64(1).to_bytes(4, "big"),
            None,
        )
        dic = {ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_block_age(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_1.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, uint64(5).to_bytes(4, "big"), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )
        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_age(self, two_nodes):
        num_blocks = 4

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, uint64(3).to_bytes(4, "big"), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_my_id(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID, block.get_coinbase().name(), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_my_id(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID,
            blocks[2].get_coinbase().name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_assert_time_exceeds(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        time_now = uint64(int(time() * 1000))

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS, time_now.to_bytes(8, "big"), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_assert_time_exceeds_both_cases(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        time_now = uint64(int(time() * 1000))
        time_now_plus_3 = time_now + 3000

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS,
            time_now_plus_3.to_bytes(8, "big"),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        # Sleep so that 3 sec passes
        await asyncio.sleep(3)

        tx2: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx2, None)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_coin_consumed(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        block2 = blocks[2]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED,
            block2.get_coinbase().name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        spend_bundle2 = generate_test_spend_bundle(block2.get_coinbase())

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(bundle)
        )
        await full_node_1.respond_transaction(tx1, None)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(
            bundle.name()
        )

        assert mempool_bundle is bundle

    @pytest.mark.asyncio
    async def test_invalid_coin_consumed(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        block2 = blocks[2]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED,
            block2.get_coinbase().name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic)

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )
        await full_node_1.respond_transaction(tx1, None)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_assert_fee_condition(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_FEE,
            int_to_bytes(10),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic, 10)

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )

        await full_node_1.respond_transaction(tx1, None)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is not None

    @pytest.mark.asyncio
    async def test_assert_fee_condition_wrong_fee(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_FEE,
            int_to_bytes(10),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic, 9)

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )

        await full_node_1.respond_transaction(tx1, None)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_stealing_fee(self, two_nodes):
        receiver_puzzlehash = BURN_PUZZLE_HASH
        num_blocks = 2
        wallet_receiver = bt.get_farmer_wallet_tool()

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, blocks, 10, b"")

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        wallet_2_block = blocks[3]

        for b in blocks:
            await full_node_1.full_node._respond_block(
                full_node_protocol.RespondBlock(b)
            )

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_FEE,
            int_to_bytes(10),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        fee = 9
        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase(), dic, fee)

        wallet_2_fees = wallet_2_block.get_fees_coin()
        steal_fee_spendbundle = wallet_receiver.generate_signed_transaction(
            wallet_2_fees.amount + fee - 4, receiver_puzzlehash, wallet_2_fees
        )

        assert spend_bundle1 is not None
        assert steal_fee_spendbundle is not None

        combined = SpendBundle.aggregate([spend_bundle1, steal_fee_spendbundle])

        assert combined.fees() == 4

        tx1: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle1)
        )

        await full_node_1.respond_transaction(tx1, None)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_double_spend_same_bundle(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_1.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        spend_bundle1 = generate_test_spend_bundle(block.get_coinbase())

        assert spend_bundle1 is not None

        spend_bundle2 = generate_test_spend_bundle(
            block.get_coinbase(),
            newpuzzlehash=BURN_PUZZLE_HASH_2,
        )

        assert spend_bundle2 is not None

        spend_bundle_combined = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle_combined)
        )

        await full_node_1.respond_transaction(tx, None)

        sb = full_node_1.full_node.mempool_manager.get_spendbundle(
            spend_bundle_combined.name()
        )
        assert sb is None

    @pytest.mark.asyncio
    async def test_agg_sig_condition(self, two_nodes):
        num_blocks = 2

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        await full_node_1.full_node._respond_block(
            full_node_protocol.RespondBlock(block)
        )

        # this code has been changed to use generate_test_spend_bundle
        # not quite sure why all the gymnastics are being performed
        spend_bundle_0 = generate_test_spend_bundle(
            block.get_coinbase(),
        )
        unsigned: List[CoinSolution] = spend_bundle_0.coin_solutions

        assert len(unsigned) == 1
        coin_solution = unsigned[0]

        err, con, cost = conditions_for_solution(coin_solution.solution)
        assert con is not None

        puzzle, solution = list(coin_solution.solution.as_iter())
        conditions_dict = conditions_by_opcode(con)
        pkm_pairs = pkm_pairs_for_conditions_dict(
            conditions_dict, coin_solution.coin.name()
        )
        assert len(pkm_pairs) == 1

        assert (
            pkm_pairs[0][1]
            == solution.rest().first().get_tree_hash() + coin_solution.coin.name()
        )

        spend_bundle = WALLET_A.sign_transaction(unsigned)
        assert spend_bundle is not None

        tx: full_node_protocol.RespondTransaction = (
            full_node_protocol.RespondTransaction(spend_bundle)
        )
        await full_node_1.respond_transaction(tx, None)

        sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle
