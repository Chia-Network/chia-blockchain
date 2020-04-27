import asyncio
import time

import pytest

from src.types.peer_info import PeerInfo
from src.protocols import full_node_protocol
from src.util.ints import uint16, uint64
from tests.setup_nodes import setup_two_nodes, setup_node_and_wallet, test_constants, bt
from src.types.spend_bundle import SpendBundle
from src.util.bundle_tools import best_solution_program
from tests.wallet_tools import WalletTool
from src.types.coin import Coin
from src.consensus.coinbase import create_coinbase_coin


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletNode:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_node_and_wallet(dic={"COINBASE_FREEZE_PERIOD": 0}):
            yield _

    @pytest.mark.asyncio
    async def test_respond_peers(self, wallet_node):
        num_blocks = 25
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [])
        full_node_1, wallet_node, server_1, server_2 = wallet_node

        for i in range(1, len(blocks)):
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
