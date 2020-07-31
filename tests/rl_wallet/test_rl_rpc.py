import asyncio
import pytest
from src.rpc.wallet_rpc_api import WalletRpcApi
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.coin import Coin
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from tests.setup_nodes import setup_simulators_and_wallets


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCCWallet:
    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(
                1, 3, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.mark.asyncio
    async def test_create_rl_coin(self, three_wallet_nodes):
        num_blocks = 4
        full_nodes, wallets = three_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_node_2, wallet_server_1 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await wallet_server_1.start_client(
            PeerInfo("localhost", uint16(server_1._port)), None
        )
        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        api_user = WalletRpcApi(wallet_node_1)
        val = await api_user.create_new_wallet({'wallet_type': 'rl_wallet',
                                                'rl_type': 'user'})
        assert isinstance(val, dict)
        assert val['success']
        assert val['type'] == 'RATE_LIMITED'
        pubkey = val['pubkey']

        api_admin = WalletRpcApi(wallet_node)
        val = await api_admin.create_new_wallet({'wallet_type': 'rl_wallet',
                                                 'rl_type': 'admin',
                                                 'interval': 2,
                                                 'limit': 1,
                                                 'pubkey': pubkey,      
                                                 'amount': 100})
        assert isinstance(val, dict)
        assert val['success']
        assert val['type'] == 'RATE_LIMITED'
        assert val['origin']
        assert val['pubkey']
        admin_pubkey = val['pubkey']
        origin: Coin = val['origin']

        val = await api_user.rl_set_user_info({'wallet_id': 2,
                                               'interval': 2,
                                               'limit': 1,
                                               'origin': {"parent_coin_info": origin.parent_coin_info,
                                                          "puzzle_hash": origin.puzzle_hash,
                                                          "amount": origin.amount},
                                               'admin_pubkey': admin_pubkey})
        assert val['success']

        for i in range(0, 2*num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(32 * b"\0"))

        receiving_wallet = wallet_node_2.wallet_state_manager.main_wallet
        puzzle_hash = await receiving_wallet.get_new_puzzlehash()
        val = await api_user.send_transaction({'wallet_id': 2,
                                               'amount': 1,
                                               'puzzle_hash': puzzle_hash.hex()})
        assert val['status'] == 'SUCCESS'