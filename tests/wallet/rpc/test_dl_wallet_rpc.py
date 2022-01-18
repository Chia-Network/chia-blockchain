import asyncio
import logging
import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from tests.setup_nodes import bt, setup_simulators_and_wallets, self_hostname
from tests.time_out_assert import time_out_assert
from tests.util.rpc import validate_get_routes

log = logging.getLogger(__name__)


class TestWalletRpc:
    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction(self, two_wallet_nodes, trusted):
        test_rpc_port = uint16(21529)
        test_rpc_port_2 = uint16(21536)
        test_rpc_port_node = uint16(21530)
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        initial_funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        wallet_rpc_api = WalletRpcApi(wallet_node)
        wallet_rpc_api_2 = WalletRpcApi(wallet_node_2)

        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]

        def stop_node_cb():
            pass

        full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

        rpc_cleanup_node = await start_rpc_server(
            full_node_rpc_api,
            hostname,
            daemon_port,
            test_rpc_port_node,
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        rpc_cleanup = await start_rpc_server(
            wallet_rpc_api,
            hostname,
            daemon_port,
            test_rpc_port,
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        rpc_cleanup = await start_rpc_server(
            wallet_rpc_api_2,
            hostname,
            daemon_port,
            test_rpc_port_2,
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )

        await time_out_assert(5, wallet.get_confirmed_balance, initial_funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, initial_funds)

        client = await WalletRpcClient.create(self_hostname, test_rpc_port, bt.root_path, config)
        await validate_get_routes(client, wallet_rpc_api)
        client_2 = await WalletRpcClient.create(self_hostname, test_rpc_port_2, bt.root_path, config)
        await validate_get_routes(client_2, wallet_rpc_api_2)

        wsm = wallet_node.wallet_state_manager

        try:
            merkle_root: bytes32 = bytes32([0] * 32)
            txs, launcher_id = await client.create_new_dl(merkle_root, uint64(50))

            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)

            async def is_singleton_confirmed(rpc_client, lid) -> bool:
                rec = await rpc_client.dl_latest_singleton(lid)
                if rec is None:
                    return False
                return rec.confirmed

            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id)
            singleton_record: SingletonRecord = await client.dl_latest_singleton(launcher_id)
            assert singleton_record.root == merkle_root

            new_root: bytes32 = bytes32([1] * 32)
            tx: TransactionRecord = await client.dl_update_root(launcher_id, new_root)

            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)

            new_singleton_record: SingletonRecord = await client.dl_latest_singleton(launcher_id)
            assert new_singleton_record.root == new_root
            assert new_singleton_record.confirmed

            assert await client.dl_history(launcher_id) == [singleton_record, new_singleton_record]

            await client_2.dl_track_new(launcher_id)

            async def is_singleton_generation(rpc_client, lid, generation) -> bool:
                if await is_singleton_confirmed(rpc_client, lid):
                    rec = await rpc_client.dl_latest_singleton(lid)
                    return rec.generation == generation
            await time_out_assert(15, is_singleton_generation, True, client_2, launcher_id, 1)
            assert await client_2.dl_history(launcher_id) == [singleton_record, new_singleton_record]
        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            await client.await_closed()
            await rpc_cleanup()
            await rpc_cleanup_node()
