import asyncio
from time import time

import pytest

from src.server.outbound_message import OutboundMessage
from src.protocols import full_node_protocol
from src.types.ConditionVarPair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
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
        num_blocks = 3
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        print(f"block coinbase: {block.body.coinbase.name()}")
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(block)
        ):
            pass

        spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.body.coinbase
        )
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle
        )
        async for _ in full_node_1.respond_transaction(tx):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb = await full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_coinbase_freeze(self, two_nodes_standard_freeze):
        num_blocks = 3
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
            1000, receiver_puzzlehash, block.body.coinbase
        )
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle
        )

        async for _ in full_node_1.respond_transaction(tx):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb = await full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
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
        print(blocks[1].body.coinbase.name())
        sb = await full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_double_spend(self, two_nodes):
        num_blocks = 3
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
            1000, receiver_puzzlehash, block.body.coinbase
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
            1000, other_receiver.get_new_puzzlehash(), block.body.coinbase
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle2
        )
        async for _ in full_node_1.respond_transaction(tx2):
            pass

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 == spend_bundle1
        assert sb2 is None

    @pytest.mark.asyncio
    async def test_double_spend_with_higher_fee(self, two_nodes):
        num_blocks = 3
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
            1000, receiver_puzzlehash, block.body.coinbase
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
            1000, receiver_puzzlehash, block.body.coinbase, fee=1
        )

        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle2
        )
        async for _ in full_node_1.respond_transaction(tx2):
            pass

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert sb1 is None
        assert sb2 == spend_bundle2

    @pytest.mark.asyncio
    async def test_invalid_block_index(self, two_nodes):
        num_blocks = 3
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
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_correct_block_index(self, two_nodes):
        num_blocks = 3
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
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_block_age(self, two_nodes):
        num_blocks = 3
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
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

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
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_correct_my_id(self, two_nodes):
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
            ConditionOpcode.ASSERT_MY_COIN_ID, block.body.coinbase.name(), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_invalid_my_id(self, two_nodes):
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
            ConditionOpcode.ASSERT_MY_COIN_ID, blocks[2].body.coinbase.name(), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function != "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None

    @pytest.mark.asyncio
    async def test_assert_time_exceeds(self, two_nodes):
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

        time_now = uint64(int(time() * 1000))

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS, time_now.to_bytes(8, "big"), None
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1

    @pytest.mark.asyncio
    async def test_assert_time_exceeds_both_cases(self, two_nodes):
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

        time_now = uint64(int(time() * 1000))
        time_now_plus_3 = time_now + 3000

        cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS,
            time_now_plus_3.to_bytes(8, "big"),
            None,
        )
        dic = {cvp.opcode: [cvp]}

        spend_bundle1 = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block.body.coinbase, dic
        )

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx1):
            outbound: OutboundMessage = _
            assert outbound.message.function != "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is None
        # Sleep so that 3 sec passes
        await asyncio.sleep(3)

        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle1
        )
        async for _ in full_node_1.respond_transaction(tx2):
            outbound_2: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound_2.message.function == "new_transaction"

        sb1 = await full_node_1.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert sb1 is spend_bundle1
