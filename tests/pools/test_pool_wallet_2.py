import asyncio
import logging

import pytest

from chia.pools.pool_wallet import PoolWallet
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets


log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestPoolWallet2:
    @pytest.fixture(scope="function")
    async def one_wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.mark.asyncio
    async def test_create_new_pool_wallet(self, one_wallet_node):
        full_nodes, wallets = one_wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        wsm = wallet_node_0.wallet_state_manager

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        for i in range(3):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await PoolWallet.create(
            wsm,
            wallet_0,
        )
