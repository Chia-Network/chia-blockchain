import asyncio
import pytest
from src.server.outbound_message import OutboundMessage
from src.protocols import peer_protocol
from src.wallet.wallets.standard_wallet.wallet import Wallet
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.wallet_tools import WalletTool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestMempool:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes():
            yield _

    @pytest.mark.asyncio
    async def test_basic_mempool(self, two_nodes):
        num_blocks = 3
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = Wallet()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.block(peer_protocol.Block(block)):
            spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, [block.body.coinbase])
            tx: peer_protocol.Transaction = peer_protocol.Transaction(spend_bundle)
            async for _ in full_node_1.transaction(tx):
                outbound: OutboundMessage = _
                # Maybe transaction means that it's accepted in mempool
                assert outbound.message.function == "maybe_transaction"

    @pytest.mark.asyncio
    async def test_double_spend(self, two_nodes):
        num_blocks = 3
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.block(peer_protocol.Block(block)):
            pass

        spend_bundle1 = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, [block.body.coinbase])
        tx1: peer_protocol.Transaction = peer_protocol.Transaction(spend_bundle1)
        async for _ in full_node_1.transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "maybe_transaction"

        other_receiver = WalletTool()
        spend_bundle2 = wallet_a.generate_signed_transaction(1000, other_receiver.get_new_puzzlehash(), [block.body.coinbase])
        tx2: peer_protocol.Transaction = peer_protocol.Transaction(spend_bundle2)
        async for _ in full_node_1.transaction(tx2):
            pass

        sb1 = await full_node_1.mempool.get_spendbundle(spend_bundle1.name())
        sb2 = await full_node_1.mempool.get_spendbundle(spend_bundle2.name())

        assert sb1 == spend_bundle1
        assert sb2 is None

    @pytest.mark.asyncio
    async def test_double_spend_with_higher_fee(self, two_nodes):
        num_blocks = 3
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        block = blocks[1]
        async for _ in full_node_1.block(peer_protocol.Block(block)):
            pass

        spend_bundle1 = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, [block.body.coinbase])
        tx1: peer_protocol.Transaction = peer_protocol.Transaction(spend_bundle1)
        async for _ in full_node_1.transaction(tx1):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "maybe_transaction"

        spend_bundle2 = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, [block.body.coinbase], 1)

        tx2: peer_protocol.Transaction = peer_protocol.Transaction(spend_bundle2)
        async for _ in full_node_1.transaction(tx2):
            pass

        sb1 = await full_node_1.mempool.get_spendbundle(spend_bundle1.name())
        sb2 = await full_node_1.mempool.get_spendbundle(spend_bundle2.name())

        assert sb1 is None
        assert sb2 == spend_bundle2

