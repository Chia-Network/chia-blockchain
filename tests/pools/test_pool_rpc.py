from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import pytest
import pytest_asyncio
from blspy import G1Element

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node import FullNode
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH
from chia.pools.pool_wallet_info import PoolSingletonState, PoolWalletInfo
from chia.protocols import full_node_protocol
from chia.protocols.full_node_protocol import RespondBlock
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools, get_plot_dir
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import setup_simulators_and_wallets_service
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.derive_keys import find_authentication_sk, find_owner_sk
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_node import WalletNode
from tests.util.wallet_is_synced import wallet_is_synced

# TODO: Compare deducted fees in all tests against reported total_fee

log = logging.getLogger(__name__)
FEE_AMOUNT = uint64(2000000000000)
MAX_WAIT_SECS = 30  # A high value for WAIT_SECS is useful when paused in the debugger


def get_pool_plot_dir() -> Path:
    return get_plot_dir() / Path("pool_tests")


async def get_total_block_rewards(num_blocks: int) -> int:
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    return funds


async def farm_blocks(full_node_api: FullNodeSimulator, ph: bytes32, num_blocks: int) -> int:
    for i in range(num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    return num_blocks
    # TODO also return calculated block rewards


@dataclass(frozen=True)
class TemporaryPoolPlot:
    bt: BlockTools
    p2_singleton_puzzle_hash: bytes32
    plot_id: bytes32


@contextlib.asynccontextmanager
async def manage_temporary_pool_plot(
    bt: BlockTools,
    p2_singleton_puzzle_hash: bytes32,
) -> AsyncIterator[TemporaryPoolPlot]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path: Path = Path(tmpdir)
        bt.add_plot_directory(tmp_path)
        plot_id = await bt.new_plot(p2_singleton_puzzle_hash, tmp_path, tmp_dir=tmp_path)
        assert plot_id is not None
        await bt.refresh_plots()

        plot = TemporaryPoolPlot(bt=bt, p2_singleton_puzzle_hash=p2_singleton_puzzle_hash, plot_id=plot_id)

        try:
            yield plot
        finally:
            await bt.delete_plot(plot_id)


PREFARMED_BLOCKS = 4


OneWalletNodeAndRpc = Tuple[WalletRpcClient, Any, FullNodeSimulator, BlockTools]


@pytest_asyncio.fixture(scope="function")
async def one_wallet_node_and_rpc(
    self_hostname: str,
) -> AsyncIterator[OneWalletNodeAndRpc]:
    rmtree(get_pool_plot_dir(), ignore_errors=True)
    async for nodes in setup_simulators_and_wallets_service(1, 1, {}):
        full_nodes, wallets, bt = nodes
        full_node_api = full_nodes[0]._api
        wallet_service = wallets[0]
        wallet_node_0 = wallet_service._node
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        our_ph = await wallet_0.get_new_puzzlehash()
        await farm_blocks(full_node_api, our_ph, PREFARMED_BLOCKS)
        assert wallet_service.rpc_server is not None
        client = await WalletRpcClient.create(
            self_hostname, wallet_service.rpc_server.listen_port, wallet_service.root_path, wallet_service.config
        )

        yield client, wallet_node_0, full_node_api, bt

        client.close()
        await client.await_closed()


Setup = Tuple[List[FullNodeSimulator], List[WalletNode], List[bytes32], WalletRpcClient]


@pytest_asyncio.fixture(scope="function")
async def setup(
    two_wallet_nodes_services: Tuple[List[Service[FullNode]], List[Service[WalletNode]], BlockTools],
    self_hostname: str,
) -> Setup:
    rmtree(get_pool_plot_dir(), ignore_errors=True)
    full_nodes, wallets, bt = two_wallet_nodes_services
    full_node_apis: List[FullNodeSimulator] = [full_node_service._api for full_node_service in full_nodes]
    wallet_service_0 = wallets[0]
    wallet_service_1 = wallets[1]
    wallet_node_0 = wallet_service_0._node
    wallet_node_1 = wallet_service_1._node
    our_ph_record = await wallet_node_0.wallet_state_manager.get_unused_derivation_record(uint32(1), hardened=True)
    pool_ph_record = await wallet_node_1.wallet_state_manager.get_unused_derivation_record(uint32(1), hardened=True)
    our_ph = our_ph_record.puzzle_hash
    pool_ph = pool_ph_record.puzzle_hash

    wallet_server_0 = wallet_service_0.rpc_server
    assert wallet_server_0 is not None

    client = await WalletRpcClient.create(
        self_hostname, wallet_server_0.listen_port, wallet_service_0.root_path, wallet_service_0.config
    )

    wallet_nodes = [wallet_node_0, wallet_node_1]

    return (
        full_node_apis,
        wallet_nodes,
        [our_ph, pool_ph],
        client,  # wallet rpc client
    )


class TestPoolWalletRpc:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_create_new_pool_wallet_self_farm(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        trusted, fee = trusted_and_fee
        client, wallet_node_0, full_node_api, _ = one_wallet_node_and_rpc
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await wallet_node_0.server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )
        total_block_rewards = await get_total_block_rewards(PREFARMED_BLOCKS)
        await time_out_assert(20, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(
            20, wallet_node_0.wallet_state_manager.blockchain.get_finished_sync_up_to, PREFARMED_BLOCKS
        )

        our_ph = await wallet_0.get_new_puzzlehash()
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0
        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )
        await time_out_assert(
            10,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            creation_tx.spend_bundle,
            creation_tx.name,
        )

        await farm_blocks(full_node_api, our_ph, 6)
        assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

        await time_out_assert(30, wallet_is_synced, True, wallet_node_0, full_node_api)
        summaries_response = await client.get_wallets(WalletType.POOLING_WALLET)
        assert len(summaries_response) == 1
        wallet_id: int = summaries_response[0]["id"]
        status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]

        assert status.current.state == PoolSingletonState.SELF_POOLING.value
        assert status.target is None
        assert status.current.owner_pubkey == G1Element.from_bytes(
            bytes.fromhex(
                "b286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304"
            )
        )
        assert status.current.pool_url == ""
        assert status.current.relative_lock_height == 0
        assert status.current.version == 1
        # Check that config has been written properly
        full_config: Dict[str, Any] = load_config(wallet_0.wallet_state_manager.root_path, "config.yaml")
        pool_list: List[Dict[str, Any]] = full_config["pool"]["pool_list"]
        assert len(pool_list) == 1
        pool_config = pool_list[0]
        assert (
            pool_config["owner_public_key"]
            == "0xb286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304"
        )
        # It can be one of multiple launcher IDs, due to selecting a different coin
        launcher_id = None
        for addition in creation_tx.additions:
            if addition.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                launcher_id = addition.name()
                break
        assert hexstr_to_bytes(pool_config["launcher_id"]) == launcher_id
        assert pool_config["pool_url"] == ""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_create_new_pool_wallet_farm_to_pool(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        trusted, fee = trusted_and_fee
        client, wallet_node_0, full_node_api, _ = one_wallet_node_and_rpc
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await wallet_node_0.server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )
        total_block_rewards = await get_total_block_rewards(PREFARMED_BLOCKS)
        await time_out_assert(
            20, wallet_node_0.wallet_state_manager.blockchain.get_finished_sync_up_to, PREFARMED_BLOCKS
        )

        await time_out_assert(20, wallet_0.get_confirmed_balance, total_block_rewards)

        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

        our_ph = await wallet_0.get_new_puzzlehash()
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "http://pool.example.com", uint32(10), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
        )
        await time_out_assert(
            10,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            creation_tx.spend_bundle,
            creation_tx.name,
        )

        await farm_blocks(full_node_api, our_ph, 6)
        assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
        summaries_response = await client.get_wallets(WalletType.POOLING_WALLET)
        assert len(summaries_response) == 1
        wallet_id: int = summaries_response[0]["id"]
        status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]

        assert status.current.state == PoolSingletonState.FARMING_TO_POOL.value
        assert status.target is None
        assert status.current.owner_pubkey == G1Element.from_bytes(
            bytes.fromhex(
                "b286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304"
            )
        )
        assert status.current.pool_url == "http://pool.example.com"
        assert status.current.relative_lock_height == 10
        assert status.current.version == 1
        # Check that config has been written properly
        full_config: Dict[str, Any] = load_config(wallet_0.wallet_state_manager.root_path, "config.yaml")
        pool_list: List[Dict[str, Any]] = full_config["pool"]["pool_list"]
        assert len(pool_list) == 1
        pool_config = pool_list[0]
        assert (
            pool_config["owner_public_key"]
            == "0xb286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304"
        )
        # It can be one of multiple launcher IDs, due to selecting a different coin
        launcher_id = None
        for addition in creation_tx.additions:
            if addition.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                launcher_id = addition.name()
                break
        assert hexstr_to_bytes(pool_config["launcher_id"]) == launcher_id
        assert pool_config["pool_url"] == "http://pool.example.com"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_create_multiple_pool_wallets(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        trusted, fee = trusted_and_fee
        client, wallet_node_0, full_node_api, _ = one_wallet_node_and_rpc
        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await wallet_node_0.server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )
        total_block_rewards = await get_total_block_rewards(PREFARMED_BLOCKS)
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        await time_out_assert(20, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(
            20, wallet_node_0.wallet_state_manager.blockchain.get_finished_sync_up_to, PREFARMED_BLOCKS
        )
        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

        our_ph_1 = await wallet_0.get_new_puzzlehash()
        our_ph_2 = await wallet_0.get_new_puzzlehash()
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph_1, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )
        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
        creation_tx_2: TransactionRecord = await client.create_new_pool_wallet(
            our_ph_1, self_hostname, uint32(12), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
        )

        await time_out_assert(
            10,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            creation_tx.spend_bundle,
            creation_tx.name,
        )
        await time_out_assert(
            10,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            creation_tx_2.spend_bundle,
            creation_tx_2.name,
        )

        await farm_blocks(full_node_api, our_ph_2, 6)
        assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None
        assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx_2.name) is None

        async def pw_created(check_wallet_id: int) -> bool:
            try:
                await client.pw_status(check_wallet_id)
                return True
            except ValueError:
                return False

        await time_out_assert(10, pw_created, True, 2)
        await time_out_assert(10, pw_created, True, 3)
        status_2: PoolWalletInfo = (await client.pw_status(2))[0]
        status_3: PoolWalletInfo = (await client.pw_status(3))[0]

        if status_2.current.state == PoolSingletonState.SELF_POOLING.value:
            assert status_3.current.state == PoolSingletonState.FARMING_TO_POOL.value
        else:
            assert status_2.current.state == PoolSingletonState.FARMING_TO_POOL.value
            assert status_3.current.state == PoolSingletonState.SELF_POOLING.value

        full_config = load_config(wallet_0.wallet_state_manager.root_path, "config.yaml")
        pool_list: List[Dict[str, Any]] = full_config["pool"]["pool_list"]
        assert len(pool_list) == 2

        assert len(await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0
        assert len(await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(3)) == 0
        # Doing a reorg reverts and removes the pool wallets
        await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(uint32(0), uint32(20), our_ph_2, None))
        await time_out_assert(30, wallet_is_synced, True, wallet_node_0, full_node_api)
        summaries_response = await client.get_wallets()
        assert len(summaries_response) == 1

        with pytest.raises(ValueError):
            await client.pw_status(2)
        with pytest.raises(ValueError):
            await client.pw_status(3)

        # Create some CAT wallets to increase wallet IDs
        def mempool_not_empty() -> bool:
            return len(full_node_api.full_node.mempool_manager.mempool.spends.keys()) > 0

        def mempool_empty() -> bool:
            return len(full_node_api.full_node.mempool_manager.mempool.spends.keys()) == 0

        await client.delete_unconfirmed_transactions(1)
        await farm_blocks(full_node_api, our_ph_2, 1)
        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

        for i in range(5):
            await time_out_assert(10, mempool_empty)
            res = await client.create_new_cat_and_wallet(uint64(20))
            summaries_response = await client.get_wallets()
            assert res["success"]
            cat_0_id = res["wallet_id"]
            asset_id = bytes.fromhex(res["asset_id"])
            assert len(asset_id) > 0
            await time_out_assert(10, mempool_not_empty)
            await farm_blocks(full_node_api, our_ph_2, 1)
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            bal_0 = await client.get_wallet_balance(cat_0_id)
            assert bal_0["confirmed_wallet_balance"] == 20

        # Test creation of many pool wallets. Use untrusted since that is the more complicated protocol, but don't
        # run this code more than once, since it's slow.
        if not trusted:
            for i in range(22):
                await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
                creation_tx_3: TransactionRecord = await client.create_new_pool_wallet(
                    our_ph_1, self_hostname, uint32(5), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
                )
                await time_out_assert(
                    10,
                    full_node_api.full_node.mempool_manager.get_spendbundle,
                    creation_tx_3.spend_bundle,
                    creation_tx_3.name,
                )
                await farm_blocks(full_node_api, our_ph_2, 2)
                await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

                full_config = load_config(wallet_0.wallet_state_manager.root_path, "config.yaml")
                pool_list = full_config["pool"]["pool_list"]
                assert len(pool_list) == i + 3
                if i == 0:
                    # Ensures that the CAT creation does not cause pool wallet IDs to increment
                    for wallet in wallet_node_0.wallet_state_manager.wallets.values():
                        if wallet.type() == WalletType.POOLING_WALLET:
                            status: PoolWalletInfo = (await client.pw_status(wallet.id()))[0]
                            assert (await wallet.get_pool_wallet_index()) < 5
                            auth_sk = find_authentication_sk(
                                [wallet_0.wallet_state_manager.private_key], status.current.owner_pubkey
                            )
                            assert auth_sk is not None
                            owner_sk = find_owner_sk(
                                [wallet_0.wallet_state_manager.private_key], status.current.owner_pubkey
                            )
                            assert owner_sk is not None
                            assert owner_sk != auth_sk

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_absorb_self(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        trusted, fee = trusted_and_fee
        client, wallet_node_0, full_node_api, _ = one_wallet_node_and_rpc
        bt = full_node_api.bt
        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await wallet_node_0.server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        total_block_rewards = await get_total_block_rewards(PREFARMED_BLOCKS)
        await time_out_assert(20, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(
            20, wallet_node_0.wallet_state_manager.blockchain.get_finished_sync_up_to, PREFARMED_BLOCKS
        )

        our_ph = await wallet_0.get_new_puzzlehash()
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )

        await time_out_assert(
            10,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            creation_tx.spend_bundle,
            creation_tx.name,
        )
        await farm_blocks(full_node_api, our_ph, 1)
        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
        status: PoolWalletInfo = (await client.pw_status(2))[0]

        assert status.current.state == PoolSingletonState.SELF_POOLING.value
        async with manage_temporary_pool_plot(bt, status.p2_singleton_puzzle_hash) as pool_plot:
            all_blocks = await full_node_api.get_all_full_blocks()
            blocks = bt.get_consecutive_blocks(
                3,
                block_list_input=all_blocks,
                force_plot_id=pool_plot.plot_id,
                farmer_reward_puzzle_hash=our_ph,
                guarantee_transaction_block=True,
            )

            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-3]))
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-2]))
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-1]))
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 2 * 1750000000000

            # Claim 2 * 1.75, and farm a new 1.75
            absorb_tx: TransactionRecord = (await client.pw_absorb_rewards(2, fee))["transaction"]
            await time_out_assert(
                5,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                absorb_tx.spend_bundle,
                absorb_tx.name,
            )
            await farm_blocks(full_node_api, our_ph, 1)
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            new_status: PoolWalletInfo = (await client.pw_status(2))[0]
            assert status.current == new_status.current
            assert status.tip_singleton_coin_id != new_status.tip_singleton_coin_id
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 1 * 1750000000000

            # Claim another 1.75
            absorb_tx1: TransactionRecord = (await client.pw_absorb_rewards(2, fee))["transaction"]

            await time_out_assert(
                MAX_WAIT_SECS,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                absorb_tx1.spend_bundle,
                absorb_tx1.name,
            )

            await farm_blocks(full_node_api, our_ph, 2)
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            assert len(await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

            tr: TransactionRecord = await client.send_transaction(
                1, uint64(100), encode_puzzle_hash(status.p2_singleton_puzzle_hash, "txch")
            )

            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                tr.spend_bundle,
                tr.name,
            )
            await farm_blocks(full_node_api, our_ph, 2)
            # Balance ignores non coinbase TX
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            with pytest.raises(ValueError):
                await client.pw_absorb_rewards(2, fee)

            tx1 = await client.get_transactions(1)
            assert (250000000000 + fee) in [tx.amount for tx in tx1]
            # await time_out_assert(20, wallet_0.get_confirmed_balance, total_block_rewards)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT * 2)])
    async def test_absorb_self_multiple_coins(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        trusted, fee = trusted_and_fee
        client, wallet_node_0, full_node_api, _ = one_wallet_node_and_rpc
        bt = full_node_api.bt
        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await wallet_node_0.server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        total_block_rewards = await get_total_block_rewards(PREFARMED_BLOCKS)
        await time_out_assert(20, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(
            20, wallet_node_0.wallet_state_manager.blockchain.get_finished_sync_up_to, PREFARMED_BLOCKS
        )

        our_ph = await wallet_0.get_new_puzzlehash()
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )

        await time_out_assert(
            10,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            creation_tx.spend_bundle,
            creation_tx.name,
        )
        await farm_blocks(full_node_api, our_ph, 1)

        async def pool_wallet_created() -> bool:
            try:
                status: PoolWalletInfo = (await client.pw_status(2))[0]
                return status.current.state == PoolSingletonState.SELF_POOLING.value
            except ValueError:
                return False

        await time_out_assert(20, pool_wallet_created)

        status: PoolWalletInfo = (await client.pw_status(2))[0]
        async with manage_temporary_pool_plot(bt, status.p2_singleton_puzzle_hash) as pool_plot:
            all_blocks = await full_node_api.get_all_full_blocks()
            blocks = bt.get_consecutive_blocks(
                3,
                block_list_input=all_blocks,
                force_plot_id=pool_plot.plot_id,
                farmer_reward_puzzle_hash=our_ph,
                guarantee_transaction_block=True,
            )

            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-3]))
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-2]))
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-1]))
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 2 * 1750000000000

            await farm_blocks(full_node_api, our_ph, 6)
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

            # Claim
            absorb_tx: TransactionRecord = (await client.pw_absorb_rewards(2, fee, 1))["transaction"]
            await time_out_assert(
                5,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                absorb_tx.spend_bundle,
                absorb_tx.name,
            )
            await farm_blocks(full_node_api, our_ph, 2)
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            new_status: PoolWalletInfo = (await client.pw_status(2))[0]
            assert status.current == new_status.current
            assert status.tip_singleton_coin_id != new_status.tip_singleton_coin_id
            main_bal = await client.get_wallet_balance(1)
            pool_bal = await client.get_wallet_balance(2)
            assert pool_bal["confirmed_wallet_balance"] == 2 * 1750000000000
            assert main_bal["confirmed_wallet_balance"] == 26499999999999

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_absorb_pooling(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        trusted, fee = trusted_and_fee
        client, wallet_node_0, full_node_api, _ = one_wallet_node_and_rpc
        bt = full_node_api.bt
        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await wallet_node_0.server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        total_block_rewards = await get_total_block_rewards(PREFARMED_BLOCKS)
        await time_out_assert(20, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(
            20, wallet_node_0.wallet_state_manager.blockchain.get_finished_sync_up_to, PREFARMED_BLOCKS
        )

        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
        our_ph = await wallet_0.get_new_puzzlehash()
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0
        # Balance stars at 6 XCH
        assert (await wallet_0.get_confirmed_balance()) == 6000000000000
        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "http://123.45.67.89", uint32(10), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
        )

        await time_out_assert(
            10,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            creation_tx.spend_bundle,
            creation_tx.name,
        )
        await farm_blocks(full_node_api, our_ph, 1)

        async def farming_to_pool() -> bool:
            try:
                status: PoolWalletInfo = (await client.pw_status(2))[0]
                return status.current.state == PoolSingletonState.FARMING_TO_POOL.value
            except ValueError:
                return False

        await time_out_assert(20, farming_to_pool)

        status: PoolWalletInfo = (await client.pw_status(2))[0]
        async with manage_temporary_pool_plot(bt, status.p2_singleton_puzzle_hash) as pool_plot:
            all_blocks = await full_node_api.get_all_full_blocks()
            blocks = bt.get_consecutive_blocks(
                3,
                block_list_input=all_blocks,
                force_plot_id=pool_plot.plot_id,
                farmer_reward_puzzle_hash=our_ph,
                guarantee_transaction_block=True,
            )

            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-3]))
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-2]))
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-1]))

            # Pooled plots don't have balance
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            # Claim 2 * 1.75, and farm a new 1.75
            absorb_tx: TransactionRecord = (await client.pw_absorb_rewards(2, fee))["transaction"]
            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                absorb_tx.spend_bundle,
                absorb_tx.name,
            )
            await farm_blocks(full_node_api, our_ph, 2)

            async def status_updated() -> bool:
                new_st: PoolWalletInfo = (await client.pw_status(2))[0]
                return status.current == new_st.current and status.tip_singleton_coin_id != new_st.tip_singleton_coin_id

            await time_out_assert(20, status_updated)
            new_status = (await client.pw_status(2))[0]
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            # Claim another 1.75
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            ret = await client.pw_absorb_rewards(2, fee)
            absorb_tx = ret["transaction"]
            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                absorb_tx.spend_bundle,
                absorb_tx.name,
            )

            if fee == 0:
                assert ret["fee_transaction"] is None
            else:
                assert ret["fee_transaction"].fee_amount == fee
            assert absorb_tx.fee_amount == fee

            await farm_blocks(full_node_api, our_ph, 2)
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0
            assert len(await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0
            peak = full_node_api.full_node.blockchain.get_peak()
            assert peak is not None
            assert await wallet_node_0.wallet_state_manager.blockchain.get_finished_sync_up_to() == peak.height
            # Balance stars at 6 XCH and 5 more blocks are farmed, total 22 XCH
            assert (await wallet_0.get_confirmed_balance()) == 21999999999999

            num_trials = 3
            status = new_status

            if fee == 0:
                for i in range(num_trials):
                    all_blocks = await full_node_api.get_all_full_blocks()
                    # Farm one block using our pool plot
                    blocks = bt.get_consecutive_blocks(
                        1,
                        block_list_input=all_blocks,
                        force_plot_id=pool_plot.plot_id,
                        farmer_reward_puzzle_hash=our_ph,
                        guarantee_transaction_block=True,
                    )
                    # Farm one more block to include the reward of the previous one
                    blocks = bt.get_consecutive_blocks(
                        1,
                        block_list_input=blocks,
                        guarantee_transaction_block=True,
                    )
                    for block in blocks[-2:]:
                        await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))
                    await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

                    # Absorb the farmed reward
                    ret = await client.pw_absorb_rewards(2, fee)
                    absorb_tx = ret["transaction"]
                    await time_out_assert(
                        5,
                        full_node_api.full_node.mempool_manager.get_spendbundle,
                        absorb_tx.spend_bundle,
                        absorb_tx.name,
                    )

                    # Confirm the absorb transaction
                    await farm_blocks(full_node_api, our_ph, 1)

                    await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
                    await time_out_assert(20, status_updated)
                    status = (await client.pw_status(2))[0]
                    assert ret["fee_transaction"] is None

            bal2 = await client.get_wallet_balance(2)
            assert bal2["confirmed_wallet_balance"] == 0
            # Note: as written, confirmed balance will not reflect on absorbs, because the fee
            # is paid back into the same client's wallet in this test.
            tx1 = await client.get_transactions(1)
            assert (250000000000 + fee) in [tx.amount for tx in tx1]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(False, uint64(0))])
    async def test_self_pooling_to_pooling(
        self,
        setup: Setup,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        """
        This tests self-pooling -> pooling
        TODO: Fix this test for a positive fee value
        """

        trusted, fee = trusted_and_fee
        num_blocks = 4  # Num blocks to farm at a time
        total_blocks = 0  # Total blocks farmed so far
        full_nodes, wallet_nodes, receive_address, client = setup
        wallets = [wallet_n.wallet_state_manager.main_wallet for wallet_n in wallet_nodes]
        wallet_node_0 = wallet_nodes[0]
        our_ph = receive_address[0]
        pool_ph = receive_address[1]
        full_node_api = full_nodes[0]
        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await wallet_node_0.server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )

        try:
            total_blocks += await farm_blocks(full_node_api, our_ph, num_blocks)
            total_block_rewards = await get_total_block_rewards(total_blocks)

            await time_out_assert(20, wallets[0].get_unconfirmed_balance, total_block_rewards)
            await time_out_assert(20, wallets[0].get_confirmed_balance, total_block_rewards)
            await time_out_assert(20, wallets[0].get_spendable_balance, total_block_rewards)
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            assert total_block_rewards > 0

            assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

            creation_tx: TransactionRecord = await client.create_new_pool_wallet(
                our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
            )
            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx.spend_bundle,
                creation_tx.name,
            )
            creation_tx_2: TransactionRecord = await client.create_new_pool_wallet(
                our_ph, "", uint32(0), f"{self_hostname}:5001", "new", "SELF_POOLING", fee
            )
            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx_2.spend_bundle,
                creation_tx_2.name,
            )

            for r in creation_tx.removals:
                assert r not in creation_tx_2.removals

            await farm_blocks(full_node_api, our_ph, 1)
            assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None
            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

            summaries_response = await client.get_wallets(WalletType.POOLING_WALLET)
            assert len(summaries_response) == 2
            wallet_id: int = summaries_response[0]["id"]
            wallet_id_2: int = summaries_response[1]["id"]
            status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            status_2: PoolWalletInfo = (await client.pw_status(wallet_id_2))[0]

            assert status.current.state == PoolSingletonState.SELF_POOLING.value
            assert status_2.current.state == PoolSingletonState.SELF_POOLING.value
            assert status.target is None
            assert status_2.target is None

            async def tx_is_in_mempool(wid: int, tx: TransactionRecord) -> bool:
                fetched: Optional[TransactionRecord] = await client.get_transaction(wid, tx.name)
                return fetched is not None and fetched.is_in_mempool()

            await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)
            join_pool: Dict[str, Any] = await client.pw_join_pool(
                wallet_id,
                pool_ph,
                "https://pool.example.com",
                uint32(10),
                fee,
            )
            assert join_pool["success"]
            join_pool_tx: TransactionRecord = join_pool["transaction"]
            assert join_pool_tx is not None
            await time_out_assert(5, tx_is_in_mempool, True, wallet_id, join_pool_tx)

            join_pool_2: Dict[str, Any] = await client.pw_join_pool(
                wallet_id_2, pool_ph, "https://pool.example.com", uint32(10), fee
            )
            assert join_pool_2["success"]
            join_pool_tx_2: TransactionRecord = join_pool_2["transaction"]
            for r in join_pool_tx.removals:
                assert r not in join_pool_tx_2.removals
            assert join_pool_tx_2 is not None
            await time_out_assert(5, tx_is_in_mempool, True, wallet_id_2, join_pool_tx_2)

            status = (await client.pw_status(wallet_id))[0]
            status_2 = (await client.pw_status(wallet_id_2))[0]

            assert status.current.state == PoolSingletonState.SELF_POOLING.value
            assert status.target is not None
            assert status.target.state == PoolSingletonState.FARMING_TO_POOL.value
            assert status_2.current.state == PoolSingletonState.SELF_POOLING.value
            assert status_2.target is not None
            assert status_2.target.state == PoolSingletonState.FARMING_TO_POOL.value

            await farm_blocks(full_node_api, our_ph, 1)

            async def status_is_farming_to_pool(w_id: int) -> bool:
                pw_status: PoolWalletInfo = (await client.pw_status(w_id))[0]
                return pw_status.current.state == PoolSingletonState.FARMING_TO_POOL.value

            await time_out_assert(20, status_is_farming_to_pool, True, wallet_id)
            await time_out_assert(20, status_is_farming_to_pool, True, wallet_id_2)
            assert len(await wallets[0].wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

        finally:
            client.close()
            await client.await_closed()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_leave_pool(
        self,
        setup: Setup,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        """This tests self-pooling -> pooling -> escaping -> self pooling"""
        trusted, fee = trusted_and_fee
        full_nodes, wallet_nodes, receive_address, client = setup
        our_ph = receive_address[0]
        wallets = [wallet_n.wallet_state_manager.main_wallet for wallet_n in wallet_nodes]
        pool_ph = receive_address[1]
        full_node_api = full_nodes[0]
        if trusted:
            wallet_nodes[0].config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_nodes[0].config["trusted_peers"] = {}

        await wallet_nodes[0].server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )

        try:
            assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

            await farm_blocks(full_node_api, our_ph, 3)

            async def have_chia() -> bool:
                return (await wallets[0].get_confirmed_balance()) > FEE_AMOUNT

            await time_out_assert(timeout=MAX_WAIT_SECS, function=have_chia)
            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            creation_tx: TransactionRecord = await client.create_new_pool_wallet(
                our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
            )

            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx.spend_bundle,
                creation_tx.name,
            )

            await farm_blocks(full_node_api, our_ph, 6)
            assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            summaries_response = await client.get_wallets(WalletType.POOLING_WALLET)
            assert len(summaries_response) == 1
            wallet_id: int = summaries_response[0]["id"]
            status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]

            assert status.current.state == PoolSingletonState.SELF_POOLING.value
            assert status.target is None

            join_pool_tx: TransactionRecord = (
                await client.pw_join_pool(
                    wallet_id,
                    pool_ph,
                    "https://pool.example.com",
                    uint32(5),
                    fee,
                )
            )["transaction"]
            assert join_pool_tx is not None

            status = (await client.pw_status(wallet_id))[0]

            assert status.current.state == PoolSingletonState.SELF_POOLING.value
            assert status.current.pool_url == ""
            assert status.current.relative_lock_height == 0
            assert status.current.state == 1
            assert status.current.version == 1

            assert status.target
            assert status.target.pool_url == "https://pool.example.com"
            assert status.target.relative_lock_height == 5
            assert status.target.state == 3
            assert status.target.version == 1

            async def status_is_farming_to_pool() -> bool:
                await farm_blocks(full_node_api, our_ph, 1)
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                return pw_status.current.state == PoolSingletonState.FARMING_TO_POOL.value

            await time_out_assert(timeout=MAX_WAIT_SECS, function=status_is_farming_to_pool)

            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            status = (await client.pw_status(wallet_id))[0]

            leave_pool_tx: Dict[str, Any] = await client.pw_self_pool(wallet_id, fee)
            assert leave_pool_tx["transaction"].wallet_id == wallet_id
            assert leave_pool_tx["transaction"].amount == 1
            await time_out_assert_not_none(
                10, full_node_api.full_node.mempool_manager.get_spendbundle, leave_pool_tx["transaction"].name
            )

            await farm_blocks(full_node_api, our_ph, 1)

            async def status_is_leaving() -> bool:
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                return pw_status.current.state == PoolSingletonState.LEAVING_POOL.value

            await time_out_assert(timeout=MAX_WAIT_SECS, function=status_is_leaving)
            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            async def status_is_self_pooling() -> bool:
                # Farm enough blocks to wait for relative_lock_height
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                log.warning(f"PW status state: {pw_status.current}")
                return pw_status.current.state == PoolSingletonState.SELF_POOLING.value

            # pass the relative lock height, this will trigger a tx.
            await farm_blocks(full_node_api, our_ph, 4)

            # Farm the TX
            for i in range(20):
                await farm_blocks(full_node_api, our_ph, 1)
                await asyncio.sleep(1)
                if await status_is_self_pooling():
                    break

            await farm_blocks(full_node_api, our_ph, 1)
            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            await time_out_assert(timeout=MAX_WAIT_SECS, function=status_is_self_pooling)
            assert len(await wallets[0].wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

        finally:
            client.close()
            await client.await_closed()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_change_pools(
        self,
        setup: Setup,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        """This tests Pool A -> escaping -> Pool B"""
        trusted, fee = trusted_and_fee
        full_nodes, wallet_nodes, receive_address, client = setup
        our_ph = receive_address[0]
        pool_a_ph = receive_address[1]
        wallets = [wallet_n.wallet_state_manager.main_wallet for wallet_n in wallet_nodes]
        pool_b_ph = await wallets[1].get_new_puzzlehash()
        full_node_api = full_nodes[0]

        if trusted:
            wallet_nodes[0].config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_nodes[0].config["trusted_peers"] = {}

        await wallet_nodes[0].server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )

        WAIT_SECS = 200
        try:
            assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

            await farm_blocks(full_node_api, our_ph, 3)

            async def have_chia() -> bool:
                return (await wallets[0].get_confirmed_balance()) > FEE_AMOUNT

            await time_out_assert(timeout=WAIT_SECS, function=have_chia)
            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            creation_tx: TransactionRecord = await client.create_new_pool_wallet(
                pool_a_ph, "https://pool-a.org", uint32(5), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
            )

            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx.spend_bundle,
                creation_tx.name,
            )

            await farm_blocks(full_node_api, our_ph, 6)
            assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            summaries_response = await client.get_wallets(WalletType.POOLING_WALLET)
            assert len(summaries_response) == 1
            wallet_id: int = summaries_response[0]["id"]
            status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]

            assert status.current.state == PoolSingletonState.FARMING_TO_POOL.value
            assert status.target is None

            async def status_is_farming_to_pool() -> bool:
                await farm_blocks(full_node_api, our_ph, 1)
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                return pw_status.current.state == PoolSingletonState.FARMING_TO_POOL.value

            await time_out_assert(timeout=WAIT_SECS, function=status_is_farming_to_pool)

            pw_info: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            assert pw_info.current.pool_url == "https://pool-a.org"
            assert pw_info.current.relative_lock_height == 5
            status = (await client.pw_status(wallet_id))[0]

            join_pool_tx: TransactionRecord = (
                await client.pw_join_pool(
                    wallet_id,
                    pool_b_ph,
                    "https://pool-b.org",
                    uint32(10),
                    fee,
                )
            )["transaction"]
            assert join_pool_tx is not None

            async def status_is_leaving() -> bool:
                await farm_blocks(full_node_api, our_ph, 1)
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                return pw_status.current.state == PoolSingletonState.LEAVING_POOL.value

            await time_out_assert(timeout=WAIT_SECS, function=status_is_leaving)
            pw_info = (await client.pw_status(wallet_id))[0]

            await time_out_assert(timeout=WAIT_SECS, function=status_is_farming_to_pool)
            pw_info = (await client.pw_status(wallet_id))[0]
            assert pw_info.current.pool_url == "https://pool-b.org"
            assert pw_info.current.relative_lock_height == 10
            assert len(await wallets[0].wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

        finally:
            client.close()
            await client.await_closed()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trusted_and_fee", [(True, FEE_AMOUNT), (False, uint64(0))])
    async def test_change_pools_reorg(
        self,
        setup: Setup,
        trusted_and_fee: Tuple[bool, uint64],
        self_hostname: str,
    ) -> None:
        """This tests Pool A -> escaping -> reorg -> escaping -> Pool B"""
        trusted, fee = trusted_and_fee
        full_nodes, wallet_nodes, receive_address, client = setup
        our_ph = receive_address[0]
        pool_a_ph = receive_address[1]
        wallets = [wallet_n.wallet_state_manager.main_wallet for wallet_n in wallet_nodes]
        pool_b_ph = await wallets[1].get_new_puzzlehash()
        full_node_api = full_nodes[0]
        WAIT_SECS = 30
        if trusted:
            wallet_nodes[0].config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_nodes[0].config["trusted_peers"] = {}

        await wallet_nodes[0].server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )

        try:
            assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

            await farm_blocks(full_node_api, our_ph, 3)

            async def have_chia() -> bool:
                return (await wallets[0].get_confirmed_balance()) > FEE_AMOUNT

            await time_out_assert(timeout=WAIT_SECS, function=have_chia)
            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            creation_tx: TransactionRecord = await client.create_new_pool_wallet(
                pool_a_ph, "https://pool-a.org", uint32(5), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
            )

            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx.spend_bundle,
                creation_tx.name,
            )

            await farm_blocks(full_node_api, our_ph, 6)
            assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

            await time_out_assert(20, wallet_is_synced, True, wallet_nodes[0], full_node_api)

            summaries_response = await client.get_wallets(WalletType.POOLING_WALLET)
            assert len(summaries_response) == 1
            wallet_id: int = summaries_response[0]["id"]
            status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]

            assert status.current.state == PoolSingletonState.FARMING_TO_POOL.value
            assert status.target is None

            async def status_is_farming_to_pool() -> bool:
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                return pw_status.current.state == PoolSingletonState.FARMING_TO_POOL.value

            await time_out_assert(timeout=WAIT_SECS, function=status_is_farming_to_pool)

            pw_info: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            assert pw_info.current.pool_url == "https://pool-a.org"
            assert pw_info.current.relative_lock_height == 5

            join_pool_tx: TransactionRecord = (
                await client.pw_join_pool(
                    wallet_id,
                    pool_b_ph,
                    "https://pool-b.org",
                    uint32(10),
                    fee,
                )
            )["transaction"]
            assert join_pool_tx is not None
            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                join_pool_tx.spend_bundle,
                join_pool_tx.name,
            )
            await farm_blocks(full_node_api, our_ph, 1)

            async def status_is_leaving_no_blocks() -> bool:
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                return pw_status.current.state == PoolSingletonState.LEAVING_POOL.value

            async def status_is_farming_to_pool_no_blocks() -> bool:
                pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
                return pw_status.current.state == PoolSingletonState.FARMING_TO_POOL.value

            await time_out_assert(timeout=WAIT_SECS, function=status_is_leaving_no_blocks)

            current_blocks = await full_node_api.get_all_full_blocks()
            more_blocks = full_node_api.bt.get_consecutive_blocks(
                3,
                farmer_reward_puzzle_hash=pool_a_ph,
                pool_reward_puzzle_hash=pool_b_ph,
                block_list_input=current_blocks[:-1],
                force_overflow=True,
                guarantee_transaction_block=True,
                seed=32 * b"4",
                transaction_data=join_pool_tx.spend_bundle,
            )

            for block in more_blocks[-3:]:
                await full_node_api.full_node.respond_block(RespondBlock(block))

            await time_out_assert(timeout=WAIT_SECS, function=status_is_leaving_no_blocks)

            for i in range(50):
                await farm_blocks(full_node_api, our_ph, 1)
                await asyncio.sleep(1)
                if await status_is_farming_to_pool():
                    break

            # Eventually, leaves pool
            assert await status_is_farming_to_pool()

        finally:
            client.close()
            await client.await_closed()
