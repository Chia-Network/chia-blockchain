import asyncio
import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.pools.pool_wallet_info import FARMING_TO_POOL, create_pool_state
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol

# from chia.types.blockchain_format.coin import Coin
# from chia.types.blockchain_format.sized_bytes import bytes32
# from chia.types.mempool_inclusion_status import MempoolInclusionStatus
# from chia.util.bech32m import encode_puzzle_hash
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
        wallet_node_0, wallet_server_0 = wallets[0]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        total_blocks += await self.farm_blocks(full_node_api, ph, num_blocks)
        total_block_rewards = await self.get_total_block_rewards(total_blocks)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet_0.get_spendable_balance, total_block_rewards)
        assert total_block_rewards > 0
        print(f"total_block_rewards: {total_block_rewards}")
        wallet_initial_confirmed_balance = await wallet_0.get_confirmed_balance()
        print(f"wallet_initial_confirmed_balance: {wallet_initial_confirmed_balance}")

        api_user = WalletRpcApi(wallet_node_0)
        our_address = ph
        initial_state = {
            "state": "SELF_POOLING",
            "target_puzzlehash": our_address.hex(),
            "pool_url": "",
            "relative_lock_height": 0,
        }
        val = await api_user.create_new_wallet(
            {
                "wallet_type": "pool_wallet",
                "mode": "new",
                "initial_target_state": initial_state,
                "host": f"{self_hostname}:5000",
            }
        )
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]
        assert val["wallet_id"] == 2
        assert val["type"] == WalletType.POOLING_WALLET.value
        assert val["current_state"] == {
            "owner_pubkey": "0x844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94",
            "pool_url": None,
            "relative_lock_height": 0,
            "state": 1,
            "target_puzzlehash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
            "version": 1,
        }
        assert val["target_state"] == {
            "owner_pubkey": "0x844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94",
            "pool_url": None,
            "relative_lock_height": 0,
            "state": 2,
            "target_puzzlehash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
            "version": 1,
        }
        assert (
            val["owner_pubkey"]
            == "844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94"
        )
        # TODO: Put the p2_puzzle_hash in the config for the plotter

    @pytest.mark.asyncio
    async def test_self_pooling_to_pooling(self, three_wallet_nodes):
        num_blocks = 4  # Num blocks to farm at a time
        total_blocks = 0  # Total blocks farmed so far
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        pool_wallet_node, pool_wallet_server = wallets[1]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        pool_wallet = pool_wallet_node.wallet_state_manager.main_wallet
        our_ph = await wallet_0.get_new_puzzlehash()
        pool_ph = await pool_wallet.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        total_blocks += await self.farm_blocks(full_node_api, our_ph, num_blocks)
        total_block_rewards = await self.get_total_block_rewards(total_blocks)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet_0.get_spendable_balance, total_block_rewards)
        assert total_block_rewards > 0
        print(f"total_block_rewards: {total_block_rewards}")
        wallet_initial_confirmed_balance = await wallet_0.get_confirmed_balance()
        print(f"wallet_initial_confirmed_balance: {wallet_initial_confirmed_balance}")

        api_user = WalletRpcApi(wallet_node_0)
        our_address = our_ph
        initial_state = {
            "state": "SELF_POOLING",
            "target_puzzlehash": our_address.hex(),
            "pool_url": None,
            "relative_lock_height": 0,
        }
        val = await api_user.create_new_wallet(
            {
                "wallet_type": "pool_wallet",
                "mode": "new",
                "initial_target_state": initial_state,
                "host": f"{self_hostname}:5000",
            }
        )
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]

        val2 = await api_user.pw_join_pool(
            {
                "wallet_id": val["id"],
                "pool_url": "https://pool.example.com",
                "relative_lock_height": 10,
                "target_puzzlehash": pool_ph.hex(),
                "host": f"{self_hostname}:5000",
            }
        )

        print(val2)

    # pooling -> escaping -> self pooling
    # Pool A -> Pool B
    # Recover pool wallet from genesis_id
