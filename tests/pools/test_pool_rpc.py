# flake8: noqa: E501
import asyncio
import logging
from typing import Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.pools.pool_wallet_info import PoolWalletInfo, PoolSingletonState
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32

from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets, bt
from tests.time_out_assert import time_out_assert


log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestPoolWalletRpc:
    @pytest.fixture(scope="function")
    async def one_wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    async def get_total_block_rewards(self, num_blocks):
        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        return funds

    async def farm_blocks(self, full_node_api, ph: bytes32, num_blocks: int):
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        return num_blocks
        # TODO also return calculated block rewards

    @pytest.mark.asyncio
    async def test_create_new_pool_wallet(self, one_wallet_node):
        num_blocks = 4  # Num blocks to farm at a time
        total_blocks = 0  # Total blocks farmed so far
        full_nodes, wallets = one_wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        our_ph = await wallet_0.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        api_user = WalletRpcApi(wallet_node_0)
        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]
        test_rpc_port = uint16(21529)

        rpc_cleanup = await start_rpc_server(
            api_user,
            hostname,
            daemon_port,
            test_rpc_port,
            lambda x: None,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        client = await WalletRpcClient.create(self_hostname, test_rpc_port, bt.root_path, config)

        try:
            total_blocks += await self.farm_blocks(full_node_api, our_ph, num_blocks)
            total_block_rewards = await self.get_total_block_rewards(total_blocks)

            await time_out_assert(10, wallet_0.get_confirmed_balance, total_block_rewards)

            summaries_response = await client.get_wallets()
            for summary in summaries_response:
                if WalletType(int(summary["type"])) == WalletType.POOLING_WALLET:
                    assert False

            creation_tx: TransactionRecord = await client.create_new_pool_wallet(
                our_ph, "", 0, "localhost:5000", "new", "SELF_POOLING"
            )

            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx.spend_bundle,
                creation_tx.name,
            )

            await self.farm_blocks(full_node_api, our_ph, 6)
            assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

            summaries_response = await client.get_wallets()
            wallet_id: Optional[int] = None
            for summary in summaries_response:
                if WalletType(int(summary["type"])) == WalletType.POOLING_WALLET:
                    wallet_id = summary["id"]
            assert wallet_id is not None

            status: PoolWalletInfo = await client.pw_status(wallet_id)

            assert status.current.state == PoolSingletonState.SELF_POOLING.value
            assert status.target is None
            assert status.current.to_json_dict() == {
                "owner_pubkey": "0xb286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304",
                "pool_url": None,
                "relative_lock_height": 0,
                "state": 1,
                "target_puzzle_hash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
                "version": 1,
            }

        finally:
            client.close()
            await client.await_closed()
            await rpc_cleanup()

    @pytest.mark.asyncio
    async def test_self_pooling_to_pooling(self, two_wallet_nodes):
        num_blocks = 4  # Num blocks to farm at a time
        total_blocks = 0  # Total blocks farmed so far
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()
        pool_ph = await wallet_1.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        api_user = WalletRpcApi(wallet_node_0)
        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]
        test_rpc_port = uint16(21529)

        rpc_cleanup = await start_rpc_server(
            api_user,
            hostname,
            daemon_port,
            test_rpc_port,
            lambda x: None,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        client = await WalletRpcClient.create(self_hostname, test_rpc_port, bt.root_path, config)

        try:
            total_blocks += await self.farm_blocks(full_node_api, ph, num_blocks)
            total_block_rewards = await self.get_total_block_rewards(total_blocks)

            await time_out_assert(10, wallet_0.get_unconfirmed_balance, total_block_rewards)
            await time_out_assert(10, wallet_0.get_confirmed_balance, total_block_rewards)
            await time_out_assert(10, wallet_0.get_spendable_balance, total_block_rewards)
            assert total_block_rewards > 0

            summaries_response = await client.get_wallets()
            for summary in summaries_response:
                if WalletType(int(summary["type"])) == WalletType.POOLING_WALLET:
                    assert False

            creation_tx: TransactionRecord = await client.create_new_pool_wallet(
                ph, "", 0, "localhost:5000", "new", "SELF_POOLING"
            )

            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx.spend_bundle,
                creation_tx.name,
            )

            await self.farm_blocks(full_node_api, ph, 6)
            assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

            summaries_response = await client.get_wallets()
            wallet_id: Optional[int] = None
            for summary in summaries_response:
                if WalletType(int(summary["type"])) == WalletType.POOLING_WALLET:
                    wallet_id = summary["id"]
            assert wallet_id is not None
            log.warning(f"PW status wallet id: {wallet_id}")
            status: PoolWalletInfo = await client.pw_status(wallet_id)
            log.warning(f"New status: {status}")

            assert status.current.state == PoolSingletonState.SELF_POOLING.value
            assert status.target is None

            state: PoolWalletInfo = await api_user.pw_join_pool(
                {
                    "wallet_id": wallet_id,
                    "pool_url": "https://pool.example.com",
                    "relative_lock_height": 10,
                    "target_puzzlehash": pool_ph.hex(),
                    "host": f"{self_hostname}:5000",
                }
            )

            status: PoolWalletInfo = await client.pw_status(wallet_id)
            log.warning(f"New status: {status}")

            assert status.current.state == PoolSingletonState.SELF_POOLING.value
            assert status.current.to_json_dict() == {
                "owner_pubkey": "0xb286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304",
                "pool_url": None,
                "relative_lock_height": 0,
                "state": 1,
                "target_puzzle_hash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
                "version": 1,
            }
            assert status.target.to_json_dict() == {
                "owner_pubkey": "0xb286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304",
                "pool_url": "https://pool.example.com",
                "relative_lock_height": 10,
                "state": 3,
                "target_puzzle_hash": "0x9ba327777484b8300d60427e4f3b776ac81948dfedd069a8d3f55834e101696e",
                "version": 1,
            }

            await self.farm_blocks(full_node_api, ph, 6)
            # assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

            status: PoolWalletInfo = await client.pw_status(wallet_id)
            log.warning(f"New status: {status}")

            assert status.current.state == PoolSingletonState.LEAVING_POOL.value
        finally:
            client.close()
            await client.await_closed()
            await rpc_cleanup()

    # pooling -> escaping -> self pooling
    # Pool A -> Pool B
    # Recover pool wallet from genesis_id
