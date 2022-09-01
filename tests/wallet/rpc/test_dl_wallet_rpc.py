import asyncio
import logging
from typing import AsyncIterator

import pytest
import pytest_asyncio

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.data_layer.data_layer_wallet import Mirror, SingletonRecord
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.db_wallet.db_wallet_puzzles import create_mirror_puzzle
from tests.setup_nodes import SimulatorsAndWallets, setup_simulators_and_wallets
from tests.util.rpc import validate_get_routes

log = logging.getLogger(__name__)


class TestWalletRpc:
    @pytest_asyncio.fixture(scope="function")
    async def two_wallet_nodes(self) -> AsyncIterator[SimulatorsAndWallets]:
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction(
        self, two_wallet_nodes: SimulatorsAndWallets, trusted: bool, self_hostname: str
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, bt = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
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

        def stop_node_cb() -> None:
            pass

        full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

        rpc_server_node = await start_rpc_server(
            full_node_rpc_api,
            hostname,
            daemon_port,
            uint16(0),
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        rpc_server_wallet_1 = await start_rpc_server(
            wallet_rpc_api,
            hostname,
            daemon_port,
            uint16(0),
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        rpc_server_wallet_2 = await start_rpc_server(
            wallet_rpc_api_2,
            hostname,
            daemon_port,
            uint16(0),
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )

        await time_out_assert(15, wallet.get_confirmed_balance, initial_funds)
        await time_out_assert(15, wallet.get_unconfirmed_balance, initial_funds)

        client = await WalletRpcClient.create(self_hostname, rpc_server_wallet_1.listen_port, bt.root_path, config)
        await validate_get_routes(client, wallet_rpc_api)
        client_2 = await WalletRpcClient.create(self_hostname, rpc_server_wallet_2.listen_port, bt.root_path, config)
        await validate_get_routes(client_2, wallet_rpc_api_2)

        try:
            merkle_root: bytes32 = bytes32([0] * 32)
            txs, launcher_id = await client.create_new_dl(merkle_root, uint64(50))

            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)

            async def is_singleton_confirmed(rpc_client: WalletRpcClient, lid: bytes32) -> bool:
                rec = await rpc_client.dl_latest_singleton(lid)
                if rec is None:
                    return False
                return rec.confirmed

            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id)
            singleton_record: SingletonRecord = await client.dl_latest_singleton(launcher_id)
            assert singleton_record.root == merkle_root

            new_root: bytes32 = bytes32([1] * 32)
            await client.dl_update_root(launcher_id, new_root, uint64(100))

            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)

            new_singleton_record: SingletonRecord = await client.dl_latest_singleton(launcher_id)
            assert new_singleton_record.root == new_root
            assert new_singleton_record.confirmed

            assert await client.dl_history(launcher_id) == [new_singleton_record, singleton_record]

            await client_2.dl_track_new(launcher_id)

            async def is_singleton_generation(rpc_client: WalletRpcClient, lid: bytes32, generation: int) -> bool:
                if await is_singleton_confirmed(rpc_client, lid):
                    rec = await rpc_client.dl_latest_singleton(lid)
                    if rec is None:
                        raise Exception("No latest singleton for: {lid!r}")
                    return rec.generation == generation
                else:
                    return False

            await time_out_assert(15, is_singleton_generation, True, client_2, launcher_id, 1)

            assert await client_2.dl_history(launcher_id) == [new_singleton_record, singleton_record]

            assert await client.dl_history(launcher_id, min_generation=uint32(1)) == [new_singleton_record]
            assert await client.dl_history(launcher_id, max_generation=uint32(0)) == [singleton_record]
            assert await client.dl_history(launcher_id, num_results=uint32(1)) == [new_singleton_record]
            assert await client.dl_history(launcher_id, num_results=uint32(2)) == [
                new_singleton_record,
                singleton_record,
            ]
            assert (
                await client.dl_history(
                    launcher_id,
                    min_generation=uint32(1),
                    max_generation=uint32(1),
                )
                == [new_singleton_record]
            )
            assert (
                await client.dl_history(
                    launcher_id,
                    max_generation=uint32(0),
                    num_results=uint32(1),
                )
                == [singleton_record]
            )
            assert (
                await client.dl_history(
                    launcher_id,
                    min_generation=uint32(1),
                    num_results=uint32(1),
                )
                == [new_singleton_record]
            )
            assert (
                await client.dl_history(
                    launcher_id,
                    min_generation=uint32(1),
                    max_generation=uint32(1),
                    num_results=uint32(1),
                )
                == [new_singleton_record]
            )

            assert await client.dl_singletons_by_root(launcher_id, new_root) == [new_singleton_record]

            txs, launcher_id_2 = await client.create_new_dl(merkle_root, uint64(50))
            txs, launcher_id_3 = await client.create_new_dl(merkle_root, uint64(50))

            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)

            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_2)
            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_3)

            next_root = bytes32([2] * 32)
            await client.dl_update_multiple(
                {
                    launcher_id: next_root,
                    launcher_id_2: next_root,
                    launcher_id_3: next_root,
                }
            )

            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)

            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id)
            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_2)
            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_3)

            for lid in [launcher_id, launcher_id_2, launcher_id_3]:
                rec = await client.dl_latest_singleton(lid)
                assert rec.root == next_root

            await client_2.dl_stop_tracking(launcher_id)
            assert await client_2.dl_latest_singleton(lid) is None

            owned_singletons = await client.dl_owned_singletons()
            owned_launcher_ids = sorted(singleton.launcher_id for singleton in owned_singletons)
            assert owned_launcher_ids == sorted([launcher_id, launcher_id_2, launcher_id_3])

            txs = await client.dl_new_mirror(launcher_id, uint64(1000), [b"foo", b"bar"], fee=uint64(2000000000000))
            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)
            additions = []
            for tx in txs:
                if tx.spend_bundle is not None:
                    additions.extend(tx.spend_bundle.additions())
            mirror_coin = [c for c in additions if c.puzzle_hash == create_mirror_puzzle().get_tree_hash()][0]
            mirror = Mirror(mirror_coin.name(), launcher_id, uint64(1000), [b"foo", b"bar"], True)
            await time_out_assert(15, client.dl_get_mirrors, [mirror], launcher_id)
            await client.dl_delete_mirror(mirror_coin.name(), fee=uint64(2000000000000))
            for i in range(0, 5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
                await asyncio.sleep(0.5)
            await time_out_assert(15, client.dl_get_mirrors, [], launcher_id)

        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            rpc_server_node.close()
            rpc_server_wallet_1.close()
            rpc_server_wallet_2.close()
            await client.await_closed()
            await rpc_server_node.await_closed()
            await rpc_server_wallet_1.await_closed()
            await rpc_server_wallet_2.await_closed()
