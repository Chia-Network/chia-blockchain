import asyncio
import signal
import time
from os import urandom

import pytest
from blspy import ExtendedPrivateKey

from src.protocols import full_node_protocol
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.wallet.wallet import Wallet
from tests.setup_nodes import setup_two_nodes, test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletProtocol:

    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 0}):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_connect(self, two_nodes):
        num_blocks = 10
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for i in range(1, num_blocks):
            async for _ in full_node_1.block(full_node_protocol.Block(blocks[i])):
                pass

        self.seed = urandom(1024)
        sk = bytes(ExtendedPrivateKey.from_seed(self.seed)).hex()
        key_config = {"wallet_sk": sk}

        wallet = Wallet({}, key_config)
        server = ChiaServer(8223, wallet, NodeType.WALLET)

        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

        _ = await server.start_server("127.0.0.1", wallet._on_connect)
        await asyncio.sleep(2)
        full_node_peer = PeerInfo(server_1._host, server_1._port)
        _ = await server.start_client(full_node_peer, None)

        start_unf = time.time()
        while time.time() - start_unf < 3:
            # TODO check if we've synced proof hashes and verified number of proofs
            await asyncio.sleep(0.1)

        server.close_all()
