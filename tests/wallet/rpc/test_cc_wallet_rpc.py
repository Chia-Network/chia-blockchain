import asyncio

import pytest

from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16
from chia.wallet.util.wallet_types import WalletType
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from tests.wallet.sync.test_wallet_sync import wallet_height_at_least


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCCWalletRPC:
    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.mark.asyncio
    async def test_create_cc_wallet(self, three_wallet_nodes):
        num_blocks = 4
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_node_2, wallet_server_2 = wallets[2]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        for i in range(0, num_blocks + 1):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        api_user = WalletRpcApi(wallet_node_1)
        await api_user.create_new_wallet(
            {"wallet_type": "cc_wallet", "mode": "existing", "cc_url": f"test.yostra.io", "host": "backup.chia.net"}
        )
        response = await api_user.get_wallets({})
        assert len(response["wallets"]) == 2
