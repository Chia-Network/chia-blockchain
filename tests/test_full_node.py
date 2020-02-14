import asyncio
import pytest

from src.protocols import full_node_protocol as fnp
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32, uint64
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.wallet_tools import WalletTool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def two_nodes():
    async for _ in setup_two_nodes():
        yield _


@pytest.fixture(scope="module")
def wallet_blocks():
    num_blocks = 3
    wallet_a = WalletTool()
    coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
    wallet_receiver = WalletTool()
    blocks = bt.get_consecutive_blocks(
        test_constants, num_blocks, [], 10, reward_puzzlehash=coinbase_puzzlehash
    )
    return wallet_a, wallet_receiver, blocks


class TestFullNode:
    @pytest.mark.asyncio
    async def test_new_tip(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        _, _, blocks = wallet_blocks

        for i in range(1, 3):
            async for _ in full_node_1.respond_block(fnp.RespondBlock(blocks[i])):
                pass

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        await asyncio.sleep(2)  # Allow connections to get made

        new_tip_1 = fnp.NewTip(
            blocks[-1].height, blocks[-1].weight, blocks[-1].header_hash
        )
        msgs_1 = [x async for x in full_node_1.new_tip(new_tip_1)]

        assert len(msgs_1) == 1
        assert msgs_1[0].message.data == fnp.RequestBlock(
            uint32(3), blocks[-1].header_hash
        )

        new_tip_2 = fnp.NewTip(
            blocks[-2].height, blocks[-2].weight, blocks[-2].header_hash
        )
        msgs_2 = [x async for x in full_node_1.new_tip(new_tip_2)]
        assert len(msgs_2) == 0

    @pytest.mark.asyncio
    async def test_new_transaction(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        wallet_a, wallet_receiver, blocks = wallet_blocks
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
        spent_block = blocks[1]

        spend_bundle = wallet_a.generate_signed_transaction(
            1001, receiver_puzzlehash, spent_block.body.coinbase
        )
        assert spend_bundle is not None

        tx_id_1 = spend_bundle.get_hash()
        new_transaction_1 = fnp.NewTransaction(tx_id_1, uint64(100), uint64(100))
        # Not seen
        msgs_1 = [x async for x in full_node_1.new_transaction(new_transaction_1)]
        assert len(msgs_1) == 1
        assert msgs_1[0].message.data == fnp.RequestTransaction(tx_id_1)

        respond_transaction_1 = fnp.RespondTransaction(spend_bundle)
        [x async for x in full_node_1.respond_transaction(respond_transaction_1)]

        # Already seen
        msgs_3 = [x async for x in full_node_1.new_transaction(new_transaction_1)]
        assert len(msgs_3) == 0

        # for _ in range(10):
        #     spend_bundle = wallet_a.generate_signed_transaction(
        #         1001, receiver_puzzlehash, spent_block.body.coinbase
        #     )
        #     assert spend_bundle is not None
        #     new_transaction_1 = fnp.NewTransaction(
        #         spend_bundle.get_hash(), uint64(100), uint64(100)
        #     )
        #     respond_transaction_2 = fnp.RespondTransaction(spend_bundle)
        #     [x async for x in full_node_1.respond_transaction(respond_transaction_2)]
