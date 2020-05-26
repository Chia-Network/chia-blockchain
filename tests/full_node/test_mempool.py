import asyncio
from time import time
from typing import List, Tuple

import clvm
import pytest
from clvm.casts import int_to_bytes
from clvm_tools import binutils

from src.server.outbound_message import OutboundMessage
from src.protocols import full_node_protocol
from src.types.BLSSignature import BLSSignature
from src.types.coin_solution import CoinSolution
from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.util.condition_tools import (
    conditions_for_solution,
    conditions_by_opcode,
    hash_key_pairs_for_conditions_dict,
)
from src.util.ints import uint64
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.wallet_tools import WalletTool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestMempool:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 0}):
            yield _

    @pytest.fixture(scope="function")
    async def two_nodes_standard_freeze(self):
        async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 200}):
            yield _

    @pytest.mark.asyncio
    async def test_basic_mempool(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase
        )
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle
        )
        async for _ in full_node_1.respond_transaction(tx):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb = full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_coinbase_freeze(self, two_nodes_standard_freeze):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes_standard_freeze

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase
        )
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle
        )

        async for _ in full_node_1.respond_transaction(tx):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb = full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is None

        blocks = bt.get_consecutive_blocks(
            test_constants, 200, [], 10, b"", coinbase_puzzlehash
        )

        for i in range(1, 201):
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        async for _ in full_node_1.respond_transaction(tx):
            outbound_2: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound_2.message.function == "new_transaction"
        sb = full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_double_spend(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        other_receiver = WalletTool()
        spend_bundle2 = wallet_a.generate_signed_transaction(
            1000, other_receiver.get_new_puzzlehash(), block.header.data.coinbase
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle2
        )
        async for _ in full_node_1.respond_transaction(tx2):
            pass

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 == spend_bundle1
        assert sb2 is None

    @pytest.mark.asyncio
    async def test_double_spend_with_higher_fee(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase
        )
        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        spend_bundle2 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, fee=1
        )

        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle2
        )
        async for _ in full_node_1.respond_transaction(tx2):
            pass

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 is None
        assert sb2 == spend_bundle2

    @pytest.mark.asyncio
    async def test_invalid_block_index(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS,
            uint64(2).to_bytes(4, "big"),
            None,
        )
        dic = {ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_index(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS,
            uint64(1).to_bytes(4, "big"),
            None,
        )
        dic = {ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_block_age(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, uint64(5).to_bytes(4, "big"), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_age(self, two_nodes):
        num_blocks = 4
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, uint64(3).to_bytes(4, "big"), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_my_id(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID, block.header.data.coinbase.name(), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_my_id(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID,
            blocks[2].header.data.coinbase.name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_assert_time_exceeds(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        time_now = uint64(int(time() * 1000))

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS, time_now.to_bytes(8, "big"), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_assert_time_exceeds_both_cases(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        time_now = uint64(int(time() * 1000))
        time_now_plus_3 = time_now + 3000

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS,
            time_now_plus_3.to_bytes(8, "big"),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            assert outbound.message.function != "new_transaction"

        # Sleep so that 3 sec passes
        await asyncio.sleep(3)

        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx2):
            outbound_2: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound_2.message.function == "new_transaction"

        sb1 = full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_coin_consumed(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        block2 = blocks[2]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED,
            block2.header.data.coinbase.name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        spend_bundle2 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block2.header.data.coinbase
        )

        bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            bundle
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        mempool_bundle = full_node_1.mempool_manager.get_spendbundle(bundle.name())

        assert mempool_bundle is bundle

    @pytest.mark.asyncio
    async def test_invalid_coin_consumed(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        block2 = blocks[2]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED,
            block2.header.data.coinbase.name(),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        mempool_bundle = full_node_1.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_assert_fee_condition(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(ConditionOpcode.ASSERT_FEE, int_to_bytes(10), None,)
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic, 10
        )

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )

        outbound_messages: List[OutboundMessage] = []
        async for outbound in full_node_1.respond_transaction(tx1):
            outbound_messages.append(outbound)

        new_transaction = False
        for msg in outbound_messages:
            if msg.message.function == "new_transaction":
                new_transaction = True

        assert new_transaction == True

        mempool_bundle = full_node_1.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is not None

    @pytest.mark.asyncio
    async def test_assert_fee_condition_wrong_fee(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(ConditionOpcode.ASSERT_FEE, int_to_bytes(10), None,)
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic, 9
        )

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )

        outbound_messages: List[OutboundMessage] = []
        async for outbound in full_node_1.respond_transaction(tx1):
            outbound_messages.append(outbound)

        new_transaction = False
        for msg in outbound_messages:
            if msg.message.function == "new_transaction":
                new_transaction = True

        assert new_transaction == False

        mempool_bundle = full_node_1.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_stealing_fee(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, blocks, 10, b"", receiver_puzzlehash
        )

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        wallet_2_block = blocks[3]

        for b in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(b)
            ):
                pass

        cvp = ConditionVarPair(ConditionOpcode.ASSERT_FEE, int_to_bytes(10), None,)
        dic = {cvp.opcode: [cvp]}

        fee = 9
        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, dic, fee
        )

        wallet_2_coinbase = wallet_2_block.header.data.coinbase
        steal_fee_spendbundle = wallet_receiver.generate_signed_transaction(
            wallet_2_coinbase.amount + fee, receiver_puzzlehash, wallet_2_coinbase
        )

        assert spend_bundle1 is not None
        assert steal_fee_spendbundle is not None

        combined = SpendBundle.aggregate([spend_bundle1, steal_fee_spendbundle])

        assert combined.fees() == 0

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )

        outbound_messages: List[OutboundMessage] = []
        async for outbound in full_node_1.respond_transaction(tx1):
            outbound_messages.append(outbound)

        new_transaction = False
        for msg in outbound_messages:
            if msg.message.function == "new_transaction":
                new_transaction = True

        assert new_transaction == False

        mempool_bundle = full_node_1.mempool_manager.get_spendbundle(
            spend_bundle1.name()
        )

        assert mempool_bundle is None

    @pytest.mark.asyncio
    async def test_double_spend_same_bundle(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase
        )

        assert spend_bundle1 is not None

        other_receiver = WalletTool()
        spend_bundle2 = wallet_a.generate_signed_transaction(
            1000, other_receiver.get_new_puzzlehash(), block.header.data.coinbase
        )

        assert spend_bundle2 is not None

        spend_bundle_combined = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle_combined
        )
        messages = []
        async for outbound in full_node_1.respond_transaction(tx):
            messages.append(outbound)

        sb = full_node_1.mempool_manager.get_spendbundle(spend_bundle_combined.name())
        assert sb is None

    @pytest.mark.asyncio
    async def test_agg_sig_condition(self, two_nodes):
        num_blocks = 2
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        unsigned: List[
            Tuple[Program, CoinSolution]
        ] = wallet_a.generate_unsigned_transaction(
            1000, receiver_puzzlehash, block.header.data.coinbase, {}, 0
        )
        assert len(unsigned) == 1

        puzzle, solution = unsigned[0]
        code_ = [puzzle, solution.solution]
        sexp = Program.to(code_)

        err, con, cost = conditions_for_solution(sexp)
        assert con is not None

        conditions_dict = conditions_by_opcode(con)
        hash_key_pairs = hash_key_pairs_for_conditions_dict(
            conditions_dict, solution.coin.name()
        )
        assert len(hash_key_pairs) == 1

        pk_pair: BLSSignature.PkMessagePair = hash_key_pairs[0]
        assert pk_pair.message_hash == solution.solution.first().get_tree_hash()

        spend_bundle = wallet_a.sign_transaction(unsigned)
        assert spend_bundle is not None

        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle
        )
        async for _ in full_node_1.respond_transaction(tx):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb = full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle
