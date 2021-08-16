import asyncio
import pytest
import time
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.protocols.full_node_protocol import RespondBlock
from chia.server.server import ChiaServer
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert, time_out_assert_not_none
from tests.wallet.cc_wallet.test_cc_wallet import tx_in_pool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSimulator:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}, simple_wallet=True):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes_five_freeze(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_sim_two_wallets(self):
        async for _ in setup_simulators_and_wallets(3, 2, {}):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_coinbase(self, wallet_node):
        num_blocks = 10
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), wallet_node.on_connect)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 2)
            ]
        )

        async def check_tx_are_pool_farm_rewards():
            wsm: WalletStateManager = wallet_node.wallet_state_manager
            all_txs = await wsm.get_all_transactions(1)
            expected_count = (num_blocks + 1) * 2
            if len(all_txs) != expected_count:
                return False
            pool_rewards = 0
            farm_rewards = 0

            for tx in all_txs:
                if tx.type == TransactionType.COINBASE_REWARD:
                    pool_rewards += 1
                elif tx.type == TransactionType.FEE_REWARD:
                    farm_rewards += 1

            if pool_rewards != expected_count / 2:
                return False
            if farm_rewards != expected_count / 2:
                return False
            return True

        await time_out_assert(10, check_tx_are_pool_farm_rewards, True)
        await time_out_assert(5, wallet.get_confirmed_balance, funds)
