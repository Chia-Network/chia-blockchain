import asyncio
import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
#from chia.types.blockchain_format.coin import Coin
#from chia.types.blockchain_format.sized_bytes import bytes32
#from chia.types.mempool_inclusion_status import MempoolInclusionStatus
#from chia.util.bech32m import encode_puzzle_hash
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from chia.wallet.util.wallet_types import WalletType
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestPoolWalletRpc:
    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    async def get_total_block_rewards(self, num_blocks):
        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )
        return funds

    async def farm_blocks(self, full_node_api, ph, num_blocks):
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        return num_blocks
        # TODO also return calculated block rewards

    @pytest.mark.asyncio
    async def test_create_new_pool_wallet(self, three_wallet_nodes):
        num_blocks = 4  # Num blocks to farm at a time
        total_blocks = 0  # Total blocks farmed so far
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

        #await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        #for i in range(0, num_blocks + 1):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))
        #await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        #await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        #await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        total_blocks += await self.farm_blocks(full_node_api, ph, num_blocks)
        total_block_rewards = await self.get_total_block_rewards(total_blocks)

        await time_out_assert(10, wallet.get_unconfirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet.get_confirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet.get_spendable_balance, total_block_rewards)
        assert total_block_rewards > 0
        print(f"total_block_rewards: {total_block_rewards}")
        wallet_initial_confirmed_balance = await wallet.get_confirmed_balance()
        print(f"wallet_initial_confirmed_balance: {wallet_initial_confirmed_balance}")

        api_user = WalletRpcApi(wallet_node_1)
        our_address = ph
        initial_state = {
            "state": "SELF_POOLING",
            "target_puzzlehash": our_address.hex(),
            "pool_url": "",
            "relative_lock_height": 0,
        }
        val = await api_user.create_new_wallet(
            {"wallet_type": "pool_wallet", "mode": "new", "initial_target_state": initial_state, "host": f"{self_hostname}:5000"}
        )
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]
        assert val["id"]
        assert val["type"] == WalletType.POOLING_WALLET.value
        user_wallet_id = val["id"]
        target_puzzlehash = val["target_puzzlehash"]
        #pubkey = val["pubkey"]

    # self pooling -> pooling
    # pooling -> escaping -> self pooling
    # Pool A -> Pool B
    # Recover pool wallet from genesis_id