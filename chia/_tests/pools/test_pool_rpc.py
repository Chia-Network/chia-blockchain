from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from typing import Any, AsyncIterator, Dict, List, Tuple

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest
from chia_rs import G1Element

from chia._tests.util.setup_nodes import setup_simulators_and_wallets_service
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.constants import ConsensusConstants
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH
from chia.pools.pool_wallet_info import PoolSingletonState, PoolWalletInfo
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.block_tools import BlockTools, get_plot_dir
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import ReorgProtocol
from chia.types.aliases import SimulatorFullNodeService, WalletService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.ints import uint32, uint64
from chia.wallet.derive_keys import find_authentication_sk, find_owner_sk
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_node import WalletNode

# TODO: Compare deducted fees in all tests against reported total_fee

log = logging.getLogger(__name__)
FEE_AMOUNT = uint64(29_000)
MAX_WAIT_SECS = 30  # A high value for WAIT_SECS is useful when paused in the debugger


def get_pool_plot_dir() -> Path:
    return get_plot_dir() / Path("pool_tests")


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
        bt_plot = await bt.new_plot(p2_singleton_puzzle_hash, tmp_path, tmp_dir=tmp_path)
        try:
            await bt.refresh_plots()

            plot = TemporaryPoolPlot(bt=bt, p2_singleton_puzzle_hash=p2_singleton_puzzle_hash, plot_id=bt_plot.plot_id)

            yield plot
        finally:
            await bt.delete_plot(bt_plot.plot_id)


PREFARMED_BLOCKS = 4


@pytest.fixture(scope="function", params=[False, True])
def trusted(request: SubRequest) -> bool:
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(scope="function")
def fee(trusted: bool) -> uint64:
    if trusted:
        return FEE_AMOUNT

    return uint64(0)


OneWalletNodeAndRpc = Tuple[WalletRpcClient, Any, FullNodeSimulator, int, BlockTools]


@pytest.fixture(scope="function")
async def one_wallet_node_and_rpc(
    trusted: bool, self_hostname: str, blockchain_constants: ConsensusConstants
) -> AsyncIterator[OneWalletNodeAndRpc]:
    rmtree(get_pool_plot_dir(), ignore_errors=True)
    async with setup_simulators_and_wallets_service(1, 1, blockchain_constants) as nodes:
        full_nodes, wallets, bt = nodes
        full_node_api: FullNodeSimulator = full_nodes[0]._api
        wallet_service = wallets[0]
        wallet_node = wallet_service._node
        wallet = wallet_node.wallet_state_manager.main_wallet

        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}

        await wallet_node.server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)

        balance = await full_node_api.farm_rewards_to_wallet(amount=8_000_000_000_000, wallet=wallet)
        assert wallet_service.rpc_server is not None
        client = await WalletRpcClient.create(
            self_hostname, wallet_service.rpc_server.listen_port, wallet_service.root_path, wallet_service.config
        )

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        yield client, wallet_node, full_node_api, balance, bt

        client.close()
        await client.await_closed()


Setup = Tuple[FullNodeSimulator, WalletNode, bytes32, int, WalletRpcClient]


@pytest.fixture(scope="function")
async def setup(
    one_wallet_and_one_simulator_services: Tuple[List[SimulatorFullNodeService], List[WalletService], BlockTools],
    trusted: bool,
    self_hostname: str,
) -> AsyncIterator[Setup]:
    rmtree(get_pool_plot_dir(), ignore_errors=True)
    [full_node_service], [wallet_service], bt = one_wallet_and_one_simulator_services
    full_node_api: FullNodeSimulator = full_node_service._api
    wallet_node = wallet_service._node
    our_ph_record = await wallet_node.wallet_state_manager.get_unused_derivation_record(uint32(1), hardened=True)
    our_ph = our_ph_record.puzzle_hash

    wallet_server = wallet_service.rpc_server
    assert wallet_server is not None

    client = await WalletRpcClient.create(
        self_hostname, wallet_server.listen_port, wallet_service.root_path, wallet_service.config
    )

    if trusted:
        wallet_node.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node.config["trusted_peers"] = {}

    await wallet_node.server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)

    assert wallet_node._wallet_state_manager is not None
    wallet = wallet_node._wallet_state_manager.main_wallet
    total_block_rewards = await full_node_api.farm_rewards_to_wallet(amount=8_000_000_000_000, wallet=wallet)
    await full_node_api.farm_blocks_to_wallet(count=3, wallet=wallet)

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    yield (
        full_node_api,
        wallet_node,
        our_ph,
        total_block_rewards,
        client,  # wallet rpc client
    )

    client.close()
    await client.await_closed()


class TestPoolWalletRpc:
    @pytest.mark.anyio
    async def test_create_new_pool_wallet_self_farm(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        fee: uint64,
        self_hostname: str,
    ) -> None:
        client, wallet_node, full_node_api, total_block_rewards, _ = one_wallet_node_and_rpc
        wallet = wallet_node.wallet_state_manager.main_wallet

        our_ph = await wallet.get_new_puzzlehash()
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0
        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )
        await full_node_api.process_transaction_records(records=[creation_tx])
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=30)

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
        full_config: Dict[str, Any] = load_config(wallet.wallet_state_manager.root_path, "config.yaml")
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

    @pytest.mark.anyio
    async def test_create_new_pool_wallet_farm_to_pool(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        fee: uint64,
        self_hostname: str,
    ) -> None:
        client, wallet_node, full_node_api, total_block_rewards, _ = one_wallet_node_and_rpc
        wallet = wallet_node.wallet_state_manager.main_wallet

        our_ph = await wallet.get_new_puzzlehash()
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "http://pool.example.com", uint32(10), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
        )
        await full_node_api.process_transaction_records(records=[creation_tx])
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

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
        full_config: Dict[str, Any] = load_config(wallet.wallet_state_manager.root_path, "config.yaml")
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

    @pytest.mark.anyio
    async def test_create_multiple_pool_wallets(
        self,
        one_wallet_node_and_rpc: OneWalletNodeAndRpc,
        trusted: bool,
        fee: uint64,
        self_hostname: str,
    ) -> None:
        client, wallet_node, full_node_api, total_block_rewards, _ = one_wallet_node_and_rpc

        wallet = wallet_node.wallet_state_manager.main_wallet

        our_ph_1 = await wallet.get_new_puzzlehash()
        our_ph_2 = await wallet.get_new_puzzlehash()
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph_1, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        creation_tx_2: TransactionRecord = await client.create_new_pool_wallet(
            our_ph_1, self_hostname, uint32(12), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
        )

        await full_node_api.process_transaction_records(records=[creation_tx, creation_tx_2])
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

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

        full_config = load_config(wallet.wallet_state_manager.root_path, "config.yaml")
        pool_list: List[Dict[str, Any]] = full_config["pool"]["pool_list"]
        assert len(pool_list) == 2

        assert len(await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0
        assert len(await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(3)) == 0
        # Doing a reorg reverts and removes the pool wallets
        await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(uint32(0), uint32(20), our_ph_2, None))
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=30)
        summaries_response = await client.get_wallets()
        assert len(summaries_response) == 1

        with pytest.raises(ValueError):
            await client.pw_status(2)
        with pytest.raises(ValueError):
            await client.pw_status(3)

        # Create some CAT wallets to increase wallet IDs
        def mempool_empty() -> bool:
            return full_node_api.full_node.mempool_manager.mempool.size() == 0

        await client.delete_unconfirmed_transactions(1)
        await full_node_api.process_all_wallet_transactions(wallet=wallet)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        for i in range(5):
            await time_out_assert(10, mempool_empty)
            res = await client.create_new_cat_and_wallet(uint64(20), test=True)
            assert res["success"]
            cat_0_id = res["wallet_id"]
            asset_id = bytes.fromhex(res["asset_id"])
            assert len(asset_id) > 0
            await full_node_api.process_all_wallet_transactions(wallet=wallet)
            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
            bal_0 = await client.get_wallet_balance(cat_0_id)
            assert bal_0["confirmed_wallet_balance"] == 20

        # Test creation of many pool wallets. Use untrusted since that is the more complicated protocol, but don't
        # run this code more than once, since it's slow.
        if not trusted:
            for i in range(22):
                await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
                creation_tx_3: TransactionRecord = await client.create_new_pool_wallet(
                    our_ph_1, self_hostname, uint32(5), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
                )
                await full_node_api.process_transaction_records(records=[creation_tx_3])
                await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

                full_config = load_config(wallet.wallet_state_manager.root_path, "config.yaml")
                pool_list = full_config["pool"]["pool_list"]
                assert len(pool_list) == i + 3
                if i == 0:
                    # Ensures that the CAT creation does not cause pool wallet IDs to increment
                    for some_wallet in wallet_node.wallet_state_manager.wallets.values():
                        if some_wallet.type() == WalletType.POOLING_WALLET:
                            status: PoolWalletInfo = (await client.pw_status(some_wallet.id()))[0]
                            assert (await some_wallet.get_pool_wallet_index()) < 5
                            auth_sk = find_authentication_sk(
                                [some_wallet.wallet_state_manager.private_key], status.current.owner_pubkey
                            )
                            assert auth_sk is not None
                            owner_sk = find_owner_sk(
                                [some_wallet.wallet_state_manager.private_key], status.current.owner_pubkey
                            )
                            assert owner_sk is not None
                            assert owner_sk[0] != auth_sk

    @pytest.mark.anyio
    async def test_absorb_self(
        self, one_wallet_node_and_rpc: OneWalletNodeAndRpc, fee: uint64, self_hostname: str
    ) -> None:
        client, wallet_node, full_node_api, total_block_rewards, _ = one_wallet_node_and_rpc
        bt = full_node_api.bt

        wallet = wallet_node.wallet_state_manager.main_wallet

        our_ph = await wallet.get_new_puzzlehash()
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )
        await full_node_api.process_transaction_records(records=[creation_tx])
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
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

            for block in blocks[-3:]:
                await full_node_api.full_node.add_block(block)
            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 2 * 1_750_000_000_000

            # Claim 2 * 1.75, and farm a new 1.75
            absorb_tx: TransactionRecord = (await client.pw_absorb_rewards(2, uint64(fee)))["transaction"]
            await full_node_api.wait_transaction_records_entered_mempool(records=[absorb_tx])
            await full_node_api.farm_blocks_to_puzzlehash(count=2, farm_to=our_ph, guarantee_transaction_blocks=True)
            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
            new_status: PoolWalletInfo = (await client.pw_status(2))[0]
            assert status.current == new_status.current
            assert status.tip_singleton_coin_id != new_status.tip_singleton_coin_id
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 1 * 1_750_000_000_000

            # Claim another 1.75
            absorb_tx1: TransactionRecord = (await client.pw_absorb_rewards(2, uint64(fee)))["transaction"]

            await full_node_api.wait_transaction_records_entered_mempool(records=[absorb_tx1])

            await full_node_api.farm_blocks_to_puzzlehash(count=2, farm_to=our_ph, guarantee_transaction_blocks=True)
            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            assert len(await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

            tr: TransactionRecord = await client.send_transaction(
                1, uint64(100), encode_puzzle_hash(status.p2_singleton_puzzle_hash, "txch"), DEFAULT_TX_CONFIG
            )

            await full_node_api.wait_transaction_records_entered_mempool(records=[tr])
            await full_node_api.farm_blocks_to_puzzlehash(count=2, farm_to=our_ph, guarantee_transaction_blocks=True)

            # Balance ignores non coinbase TX
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            with pytest.raises(ValueError):
                await client.pw_absorb_rewards(2, uint64(fee))

            tx1 = await client.get_transactions(1)
            assert (250_000_000_000 + fee) in [tx.amount for tx in tx1]

    @pytest.mark.anyio
    async def test_absorb_self_multiple_coins(
        self, one_wallet_node_and_rpc: OneWalletNodeAndRpc, fee: uint64, self_hostname: str
    ) -> None:
        client, wallet_node, full_node_api, total_block_rewards, _ = one_wallet_node_and_rpc
        bt = full_node_api.bt

        wallet = wallet_node.wallet_state_manager.main_wallet

        our_ph = await wallet.get_new_puzzlehash()
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        main_expected_confirmed_balance = total_block_rewards
        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )
        await full_node_api.process_transaction_records(records=[creation_tx])
        main_expected_confirmed_balance -= fee
        main_expected_confirmed_balance -= 1
        pool_expected_confirmed_balance = 0

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        main_bal = await client.get_wallet_balance(1)
        assert main_bal["confirmed_wallet_balance"] == main_expected_confirmed_balance

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

            block_count = 3
            for block in blocks[-block_count:]:
                await full_node_api.full_node.add_block(block)
            await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

            pool_expected_confirmed_balance += block_count * 1_750_000_000_000
            main_expected_confirmed_balance += block_count * 250_000_000_000

            main_bal = await client.get_wallet_balance(1)
            assert main_bal["confirmed_wallet_balance"] == main_expected_confirmed_balance
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == pool_expected_confirmed_balance

            # Claim
            absorb_tx: TransactionRecord = (await client.pw_absorb_rewards(2, uint64(fee), 1))["transaction"]
            await full_node_api.process_transaction_records(records=[absorb_tx])
            main_expected_confirmed_balance -= fee
            main_expected_confirmed_balance += 1_750_000_000_000
            pool_expected_confirmed_balance -= 1_750_000_000_000

            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
            new_status: PoolWalletInfo = (await client.pw_status(2))[0]
            assert status.current == new_status.current
            assert status.tip_singleton_coin_id != new_status.tip_singleton_coin_id
            main_bal = await client.get_wallet_balance(1)
            pool_bal = await client.get_wallet_balance(2)
            assert pool_bal["confirmed_wallet_balance"] == pool_expected_confirmed_balance
            assert main_bal["confirmed_wallet_balance"] == main_expected_confirmed_balance  # 10499999999999

    @pytest.mark.anyio
    async def test_absorb_pooling(
        self, one_wallet_node_and_rpc: OneWalletNodeAndRpc, fee: uint64, self_hostname: str
    ) -> None:
        client, wallet_node, full_node_api, total_block_rewards, _ = one_wallet_node_and_rpc
        bt = full_node_api.bt

        main_expected_confirmed_balance = total_block_rewards

        wallet = wallet_node.wallet_state_manager.main_wallet

        our_ph = await wallet.get_new_puzzlehash()
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0
        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "http://123.45.67.89", uint32(10), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
        )
        await full_node_api.process_transaction_records(records=[creation_tx])
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        main_expected_confirmed_balance -= 1
        main_expected_confirmed_balance -= fee

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

            block_count = 3
            for block in blocks[-block_count:]:
                await full_node_api.full_node.add_block(block)
            await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
            # Pooled plots don't have balance
            main_expected_confirmed_balance += block_count * 250_000_000_000
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            # Claim block_count * 1.75
            ret = await client.pw_absorb_rewards(2, uint64(fee))
            absorb_tx: TransactionRecord = ret["transaction"]
            if fee == 0:
                assert ret["fee_transaction"] is None
            else:
                assert ret["fee_transaction"].fee_amount == fee
            assert absorb_tx.fee_amount == fee
            await full_node_api.process_transaction_records(records=[absorb_tx])
            main_expected_confirmed_balance -= fee
            main_expected_confirmed_balance += block_count * 1_750_000_000_000

            async def status_updated() -> bool:
                new_st: PoolWalletInfo = (await client.pw_status(2))[0]
                return status.current == new_st.current and status.tip_singleton_coin_id != new_st.tip_singleton_coin_id

            await time_out_assert(20, status_updated)
            new_status = (await client.pw_status(2))[0]
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0

            await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
            bal = await client.get_wallet_balance(2)
            assert bal["confirmed_wallet_balance"] == 0
            assert len(await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0
            peak = full_node_api.full_node.blockchain.get_peak()
            assert peak is not None
            assert await wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to() == peak.height
            assert (await wallet.get_confirmed_balance()) == main_expected_confirmed_balance

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
                        await full_node_api.full_node.add_block(block)
                    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

                    # Absorb the farmed reward
                    ret = await client.pw_absorb_rewards(2, fee)
                    absorb_tx = ret["transaction"]
                    await full_node_api.process_transaction_records(records=[absorb_tx])

                    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
                    await time_out_assert(20, status_updated)
                    status = (await client.pw_status(2))[0]
                    assert ret["fee_transaction"] is None

            bal2 = await client.get_wallet_balance(2)
            assert bal2["confirmed_wallet_balance"] == 0

    @pytest.mark.anyio
    async def test_self_pooling_to_pooling(self, setup: Setup, fee: uint64, self_hostname: str) -> None:
        """
        This tests self-pooling -> pooling
        TODO: Fix this test for a positive fee value
        """

        if fee != 0:
            pytest.skip("need to fix this test for non-zero fees")

        full_node_api, wallet_node, our_ph, total_block_rewards, client = setup
        pool_ph = bytes32([0] * 32)

        assert wallet_node._wallet_state_manager is not None

        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )
        await full_node_api.wait_transaction_records_entered_mempool(records=[creation_tx])
        creation_tx_2: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5001", "new", "SELF_POOLING", fee
        )

        for r in creation_tx.removals:
            assert r not in creation_tx_2.removals

        await full_node_api.process_transaction_records(records=[creation_tx_2])

        assert not full_node_api.txs_in_mempool(txs=[creation_tx])
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

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

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
        join_pool: Dict[str, Any] = await client.pw_join_pool(
            wallet_id,
            pool_ph,
            "https://pool.example.com",
            uint32(10),
            uint64(fee),
        )
        assert join_pool["success"]
        join_pool_tx: TransactionRecord = join_pool["transaction"]
        assert join_pool_tx is not None
        await full_node_api.wait_transaction_records_entered_mempool(records=[join_pool_tx])

        join_pool_2: Dict[str, Any] = await client.pw_join_pool(
            wallet_id_2, pool_ph, "https://pool.example.com", uint32(10), uint64(fee)
        )
        assert join_pool_2["success"]
        join_pool_tx_2: TransactionRecord = join_pool_2["transaction"]
        for r in join_pool_tx.removals:
            assert r not in join_pool_tx_2.removals
        assert join_pool_tx_2 is not None
        await full_node_api.wait_transaction_records_entered_mempool(records=[join_pool_tx_2])

        status = (await client.pw_status(wallet_id))[0]
        status_2 = (await client.pw_status(wallet_id_2))[0]

        assert status.current.state == PoolSingletonState.SELF_POOLING.value
        assert status.target is not None
        assert status.target.state == PoolSingletonState.FARMING_TO_POOL.value
        assert status_2.current.state == PoolSingletonState.SELF_POOLING.value
        assert status_2.target is not None
        assert status_2.target.state == PoolSingletonState.FARMING_TO_POOL.value

        await full_node_api.process_transaction_records(records=[join_pool_tx, join_pool_tx_2])

        async def status_is_farming_to_pool(w_id: int) -> bool:
            pw_status: PoolWalletInfo = (await client.pw_status(w_id))[0]
            return pw_status.current.state == PoolSingletonState.FARMING_TO_POOL.value

        await time_out_assert(20, status_is_farming_to_pool, True, wallet_id)
        await time_out_assert(20, status_is_farming_to_pool, True, wallet_id_2)
        assert len(await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

    @pytest.mark.anyio
    async def test_leave_pool(self, setup: Setup, fee: uint64, self_hostname: str) -> None:
        """This tests self-pooling -> pooling -> escaping -> self pooling"""
        full_node_api, wallet_node, our_ph, total_block_rewards, client = setup
        pool_ph = bytes32([0] * 32)

        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            our_ph, "", uint32(0), f"{self_hostname}:5000", "new", "SELF_POOLING", fee
        )

        await full_node_api.wait_transaction_records_entered_mempool(records=[creation_tx])

        await full_node_api.farm_blocks_to_puzzlehash(count=6, farm_to=our_ph, guarantee_transaction_blocks=True)
        assert not full_node_api.txs_in_mempool(txs=[creation_tx])

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

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
            await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)
            pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            return pw_status.current.state == PoolSingletonState.FARMING_TO_POOL.value

        await time_out_assert(timeout=MAX_WAIT_SECS, function=status_is_farming_to_pool)

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        leave_pool_tx: Dict[str, Any] = await client.pw_self_pool(wallet_id, uint64(fee))
        assert leave_pool_tx["transaction"].wallet_id == wallet_id
        assert leave_pool_tx["transaction"].amount == 1
        await full_node_api.wait_transaction_records_entered_mempool(records=[leave_pool_tx["transaction"]])

        await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)

        async def status_is_leaving() -> bool:
            pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            return pw_status.current.state == PoolSingletonState.LEAVING_POOL.value

        await time_out_assert(timeout=MAX_WAIT_SECS, function=status_is_leaving)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        async def status_is_self_pooling() -> bool:
            # Farm enough blocks to wait for relative_lock_height
            pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            log.warning(f"PW status state: {pw_status.current}")
            return pw_status.current.state == PoolSingletonState.SELF_POOLING.value

        # pass the relative lock height, this will trigger a tx.
        await full_node_api.farm_blocks_to_puzzlehash(count=4, farm_to=our_ph, guarantee_transaction_blocks=True)

        # Farm the TX
        for i in range(20):
            await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)
            await asyncio.sleep(1)
            if await status_is_self_pooling():
                break

        await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        await time_out_assert(timeout=MAX_WAIT_SECS, function=status_is_self_pooling)
        assert len(await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

    @pytest.mark.anyio
    async def test_change_pools(self, setup: Setup, fee: uint64, self_hostname: str) -> None:
        """This tests Pool A -> escaping -> Pool B"""
        full_node_api, wallet_node, our_ph, total_block_rewards, client = setup
        pool_a_ph = bytes32([0] * 32)
        pool_b_ph = bytes32([0] * 32)

        WAIT_SECS = 200
        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            pool_a_ph, "https://pool-a.org", uint32(5), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", fee
        )

        await full_node_api.wait_transaction_records_entered_mempool(records=[creation_tx])

        await full_node_api.farm_blocks_to_puzzlehash(count=6, farm_to=our_ph, guarantee_transaction_blocks=True)
        assert not full_node_api.txs_in_mempool(txs=[creation_tx])

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        summaries_response = await client.get_wallets(WalletType.POOLING_WALLET)
        assert len(summaries_response) == 1
        wallet_id: int = summaries_response[0]["id"]
        status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]

        assert status.current.state == PoolSingletonState.FARMING_TO_POOL.value
        assert status.target is None

        async def status_is_farming_to_pool() -> bool:
            await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)
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
                uint64(fee),
            )
        )["transaction"]
        assert join_pool_tx is not None

        async def status_is_leaving() -> bool:
            await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)
            pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            return pw_status.current.state == PoolSingletonState.LEAVING_POOL.value

        await time_out_assert(timeout=WAIT_SECS, function=status_is_leaving)
        pw_info = (await client.pw_status(wallet_id))[0]

        await time_out_assert(timeout=WAIT_SECS, function=status_is_farming_to_pool)
        pw_info = (await client.pw_status(wallet_id))[0]
        assert pw_info.current.pool_url == "https://pool-b.org"
        assert pw_info.current.relative_lock_height == 10
        assert len(await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(2)) == 0

    @pytest.mark.anyio
    async def test_change_pools_reorg(self, setup: Setup, fee: uint64, self_hostname: str) -> None:
        """This tests Pool A -> escaping -> reorg -> escaping -> Pool B"""
        full_node_api, wallet_node, our_ph, total_block_rewards, client = setup
        pool_a_ph = bytes32([0] * 32)
        pool_b_ph = bytes32([0] * 32)
        WAIT_SECS = 30

        assert len(await client.get_wallets(WalletType.POOLING_WALLET)) == 0

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        creation_tx: TransactionRecord = await client.create_new_pool_wallet(
            pool_a_ph, "https://pool-a.org", uint32(5), f"{self_hostname}:5000", "new", "FARMING_TO_POOL", uint64(fee)
        )

        await full_node_api.wait_transaction_records_entered_mempool(records=[creation_tx])

        await full_node_api.farm_blocks_to_puzzlehash(count=6, farm_to=our_ph, guarantee_transaction_blocks=True)
        assert not full_node_api.txs_in_mempool(txs=[creation_tx])

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

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
                uint64(fee),
            )
        )["transaction"]
        assert join_pool_tx is not None
        await full_node_api.wait_transaction_records_entered_mempool(records=[join_pool_tx])
        await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)

        async def status_is_leaving_no_blocks() -> bool:
            pw_status: PoolWalletInfo = (await client.pw_status(wallet_id))[0]
            return pw_status.current.state == PoolSingletonState.LEAVING_POOL.value

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
            await full_node_api.full_node.add_block(block)

        await time_out_assert(timeout=WAIT_SECS, function=status_is_leaving_no_blocks)

        for i in range(50):
            await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=our_ph, guarantee_transaction_blocks=True)
            await asyncio.sleep(1)
            if await status_is_farming_to_pool():
                break

        # Eventually, leaves pool
        assert await status_is_farming_to_pool()
