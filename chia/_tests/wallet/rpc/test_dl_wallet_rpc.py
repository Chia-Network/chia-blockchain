from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.util.rpc import validate_get_routes
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.data_layer.data_layer_util import DLProof, HashOnlyProof, ProofLayer, StoreProofsHashes
from chia.data_layer.data_layer_wallet import Mirror
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.wallet.db_wallet.db_wallet_puzzles import create_mirror_puzzle
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.wallet_request_types import (
    CreateNewDL,
    DLDeleteMirror,
    DLGetMirrors,
    DLGetMirrorsResponse,
    DLHistory,
    DLLatestSingleton,
    DLNewMirror,
    DLSingletonsByRoot,
    DLStopTracking,
    DLTrackNew,
    DLUpdateMultiple,
    DLUpdateMultipleUpdates,
    DLUpdateRoot,
    LauncherRootPair,
)
from chia.wallet.wallet_rpc_client import WalletRpcClient

log = logging.getLogger(__name__)


class TestWalletRpc:
    @pytest.mark.parametrize("trusted", [True, False])
    @pytest.mark.anyio
    async def test_wallet_make_transaction(
        self, two_wallet_nodes_services: SimulatorsAndWalletsServices, trusted: bool, self_hostname: str
    ) -> None:
        num_blocks = 5
        [full_node_service], wallet_services, _bt = two_wallet_nodes_services
        full_node_api = full_node_service._api
        full_node_server = full_node_api.full_node.server
        wallet_node = wallet_services[0]._node
        server_2 = wallet_node.server
        wallet_node_2 = wallet_services[1]._node
        server_3 = wallet_node_2.server
        wallet = wallet_node.wallet_state_manager.main_wallet
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            ph = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)

        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        initial_funds = sum(
            calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)
        )

        await time_out_assert(15, wallet.get_confirmed_balance, initial_funds)
        await time_out_assert(15, wallet.get_unconfirmed_balance, initial_funds)

        assert wallet_services[0].rpc_server is not None
        assert wallet_services[1].rpc_server is not None

        async with contextlib.AsyncExitStack() as exit_stack:
            client = await exit_stack.enter_async_context(
                WalletRpcClient.create_as_context(
                    self_hostname,
                    wallet_services[0].rpc_server.listen_port,
                    wallet_services[0].root_path,
                    wallet_services[0].config,
                )
            )
            await validate_get_routes(client, wallet_services[0].rpc_server.rpc_api)
            client_2 = await exit_stack.enter_async_context(
                WalletRpcClient.create_as_context(
                    self_hostname,
                    wallet_services[1].rpc_server.listen_port,
                    wallet_services[1].root_path,
                    wallet_services[1].config,
                )
            )
            await validate_get_routes(client_2, wallet_services[1].rpc_server.rpc_api)

            merkle_root: bytes32 = bytes32.zeros
            launcher_id = (
                await client.create_new_dl(CreateNewDL(root=merkle_root, fee=uint64(50), push=True), DEFAULT_TX_CONFIG)
            ).launcher_id

            for i in range(5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.zeros))
                await asyncio.sleep(0.5)

            async def is_singleton_confirmed(rpc_client: WalletRpcClient, lid: bytes32) -> bool:
                rec = (await rpc_client.dl_latest_singleton(DLLatestSingleton(lid))).singleton
                if rec is None:
                    return False
                return rec.confirmed

            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id)
            singleton_record = (await client.dl_latest_singleton(DLLatestSingleton(launcher_id))).singleton
            assert singleton_record is not None
            assert singleton_record.root == merkle_root

            new_root: bytes32 = bytes32([1] * 32)
            await client.dl_update_root(
                DLUpdateRoot(launcher_id=launcher_id, new_root=new_root, fee=uint64(100), push=True), DEFAULT_TX_CONFIG
            )

            for i in range(5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.zeros))
                await asyncio.sleep(0.5)

            new_singleton_record = (await client.dl_latest_singleton(DLLatestSingleton(launcher_id))).singleton
            assert new_singleton_record is not None
            assert new_singleton_record.root == new_root
            assert new_singleton_record.confirmed

            assert (await client.dl_history(DLHistory(launcher_id))).history == [new_singleton_record, singleton_record]

            # Test tracking a launcher id that does not exist
            with pytest.raises(ValueError):
                await client_2.dl_track_new(DLTrackNew(bytes32([1] * 32)))

            await client_2.dl_track_new(DLTrackNew(launcher_id))

            async def is_singleton_generation(rpc_client: WalletRpcClient, lid: bytes32, generation: int) -> bool:
                if await is_singleton_confirmed(rpc_client, lid):
                    rec = (await rpc_client.dl_latest_singleton(DLLatestSingleton(lid))).singleton
                    if rec is None:
                        raise Exception(f"No latest singleton for: {lid!r}")
                    return rec.generation == generation
                else:
                    return False

            await time_out_assert(15, is_singleton_generation, True, client_2, launcher_id, 1)

            assert (await client_2.dl_history(DLHistory(launcher_id))).history == [
                new_singleton_record,
                singleton_record,
            ]

            assert (await client.dl_history(DLHistory(launcher_id, min_generation=uint32(1)))).history == [
                new_singleton_record
            ]
            assert (await client.dl_history(DLHistory(launcher_id, max_generation=uint32(0)))).history == [
                singleton_record
            ]
            assert (await client.dl_history(DLHistory(launcher_id, num_results=uint32(1)))).history == [
                new_singleton_record
            ]
            assert (await client.dl_history(DLHistory(launcher_id, num_results=uint32(2)))).history == [
                new_singleton_record,
                singleton_record,
            ]
            assert (
                await client.dl_history(
                    DLHistory(
                        launcher_id,
                        min_generation=uint32(1),
                        max_generation=uint32(1),
                    )
                )
            ).history == [new_singleton_record]
            assert (
                await client.dl_history(
                    DLHistory(
                        launcher_id,
                        max_generation=uint32(0),
                        num_results=uint32(1),
                    )
                )
            ).history == [singleton_record]
            assert (
                await client.dl_history(
                    DLHistory(
                        launcher_id,
                        min_generation=uint32(1),
                        num_results=uint32(1),
                    )
                )
            ).history == [new_singleton_record]
            assert (
                await client.dl_history(
                    DLHistory(
                        launcher_id,
                        min_generation=uint32(1),
                        max_generation=uint32(1),
                        num_results=uint32(1),
                    )
                )
            ).history == [new_singleton_record]

            assert (await client.dl_singletons_by_root(DLSingletonsByRoot(launcher_id, new_root))).singletons == [
                new_singleton_record
            ]

            launcher_id_2 = (
                await client.create_new_dl(CreateNewDL(root=merkle_root, fee=uint64(50), push=True), DEFAULT_TX_CONFIG)
            ).launcher_id
            launcher_id_3 = (
                await client.create_new_dl(CreateNewDL(root=merkle_root, fee=uint64(50), push=True), DEFAULT_TX_CONFIG)
            ).launcher_id

            for i in range(5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.zeros))
                await asyncio.sleep(0.5)

            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_2)
            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_3)

            next_root = bytes32([2] * 32)
            await client.dl_update_multiple(
                DLUpdateMultiple(
                    updates=DLUpdateMultipleUpdates(
                        [
                            LauncherRootPair(launcher_id, next_root),
                            LauncherRootPair(launcher_id_2, next_root),
                            LauncherRootPair(launcher_id_3, next_root),
                        ]
                    ),
                    fee=uint64(0),
                ),
                DEFAULT_TX_CONFIG,
            )

            for i in range(5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.zeros))
                await asyncio.sleep(0.5)

            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id)
            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_2)
            await time_out_assert(15, is_singleton_confirmed, True, client, launcher_id_3)

            for lid in [launcher_id, launcher_id_2, launcher_id_3]:
                rec = (await client.dl_latest_singleton(DLLatestSingleton(lid))).singleton
                assert rec is not None
                assert rec.root == next_root

            await client_2.dl_stop_tracking(DLStopTracking(launcher_id))
            assert (await client_2.dl_latest_singleton(DLLatestSingleton(lid))).singleton is None

            owned_singletons = (await client.dl_owned_singletons()).singletons
            owned_launcher_ids = sorted(singleton.launcher_id for singleton in owned_singletons)
            assert owned_launcher_ids == sorted([launcher_id, launcher_id_2, launcher_id_3])

            txs = (
                await client.dl_new_mirror(
                    DLNewMirror(
                        launcher_id=launcher_id,
                        amount=uint64(1000),
                        urls=["foo", "bar"],
                        fee=uint64(2000000000000),
                        push=True,
                    ),
                    DEFAULT_TX_CONFIG,
                )
            ).transactions
            await full_node_api.wait_transaction_records_entered_mempool(txs)
            height = full_node_api.full_node.blockchain.get_peak_height()
            assert height is not None
            for i in range(5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.zeros))
                await asyncio.sleep(0.5)
            additions = []
            for tx in txs:
                if tx.spend_bundle is not None:
                    additions.extend(tx.spend_bundle.additions())
            mirror_coin = next(c for c in additions if c.puzzle_hash == create_mirror_puzzle().get_tree_hash())
            mirror = Mirror(
                mirror_coin.name(),
                launcher_id,
                uint64(1000),
                ["foo", "bar"],
                True,
                uint32(height + 1),
            )
            await time_out_assert(15, client.dl_get_mirrors, DLGetMirrorsResponse([mirror]), DLGetMirrors(launcher_id))
            await client.dl_delete_mirror(
                DLDeleteMirror(coin_id=mirror_coin.name(), fee=uint64(2000000000000), push=True), DEFAULT_TX_CONFIG
            )
            for i in range(5):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.zeros))
                await asyncio.sleep(0.5)
            await time_out_assert(15, client.dl_get_mirrors, DLGetMirrorsResponse([]), DLGetMirrors(launcher_id))

    @pytest.mark.parametrize("trusted", [True, False])
    @pytest.mark.anyio
    async def test_wallet_dl_verify_proof(
        self, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, trusted: bool, self_hostname: str
    ) -> None:
        [full_node_service], [wallet_service], _bt = one_wallet_and_one_simulator_services
        full_node_api = full_node_service._api
        full_node_server = full_node_api.full_node.server
        wallet_node = wallet_service._node

        # Create fake proof
        # Specifically
        fakeproof = HashOnlyProof.from_key_value(
            key=b"key",
            value=b"value",
            node_hash=bytes32([1] * 32),
            layers=[
                ProofLayer(
                    other_hash_side=uint8(0),
                    other_hash=bytes32([1] * 32),
                    combined_hash=bytes32([1] * 32),
                ),
            ],
        )
        fake_coin_id = bytes32([5] * 32)
        fake_gpr = DLProof(
            store_proofs=StoreProofsHashes(store_id=bytes32([1] * 32), proofs=[fakeproof]),
            coin_id=fake_coin_id,
            inner_puzzle_hash=bytes32([1] * 32),
        )

        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        assert wallet_service.rpc_server is not None
        client = await WalletRpcClient.create(
            self_hostname,
            wallet_service.rpc_server.listen_port,
            wallet_service.root_path,
            wallet_service.config,
        )

        with pytest.raises(ValueError, match="No peer connected"):
            await wallet_service.rpc_server.rpc_api.dl_verify_proof(fake_gpr.to_json_dict())

        await wallet_node.server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await validate_get_routes(client, wallet_service.rpc_server.rpc_api)

        with pytest.raises(ValueError, match=f"Invalid Proof: No DL singleton found at coin id: {fake_coin_id}"):
            await client.dl_verify_proof(fake_gpr)
