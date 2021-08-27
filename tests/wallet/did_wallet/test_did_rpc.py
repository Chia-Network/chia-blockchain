import asyncio
import logging
import pytest

from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.util.wallet_types import WalletType
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets, bt
from tests.time_out_assert import time_out_assert
from chia.wallet.did_wallet.did_wallet import DIDWallet


log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestDIDWallet:
    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.mark.asyncio
    async def test_create_did(self, three_wallet_nodes):
        num_blocks = 4
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_node_2, wallet_server_2 = wallets[2]
        MAX_WAIT_SECS = 30

        wallet = wallet_node_0.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        for i in range(0, num_blocks + 1):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        log.info("Waiting for initial money in Wallet 0 ...")

        api_one = WalletRpcApi(wallet_node_0)
        config = bt.config
        daemon_port = config["daemon_port"]
        test_rpc_port = uint16(21529)
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        client = await WalletRpcClient.create(self_hostname, test_rpc_port, bt.root_path, bt.config)
        rpc_server_cleanup = await start_rpc_server(
            api_one,
            self_hostname,
            daemon_port,
            test_rpc_port,
            lambda x: None,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )

        async def got_initial_money():
            balances = await client.get_wallet_balance("1")
            return balances["confirmed_wallet_balance"] > 0

        await time_out_assert(timeout=MAX_WAIT_SECS, function=got_initial_money)

        val = await client.create_new_did_wallet(201)

        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]
        assert val["type"] == WalletType.DISTRIBUTED_ID.value
        assert val["wallet_id"] > 1
        assert len(val["my_did"]) == 64
        assert bytes.fromhex(val["my_did"])

        main_wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
        ph2 = await main_wallet_2.get_new_puzzlehash()
        for i in range(0, num_blocks + 1):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        recovery_list = [bytes.fromhex(val["my_did"])]
        async with wallet_node_2.wallet_state_manager.lock:
            did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_2.wallet_state_manager, main_wallet_2, uint64(101), recovery_list
            )
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        filename = "test.backup"
        did_wallet_2.create_backup(filename)

        val = await client.create_new_did_wallet_from_recovery(filename)
        if "success" in val:
            assert val["success"]
        assert val["type"] == WalletType.DISTRIBUTED_ID.value
        assert val["wallet_id"] > 1
        did_wallet_id_3 = val["wallet_id"]
        assert len(val["my_did"]) == 64
        assert bytes.fromhex(val["my_did"]) == did_wallet_2.did_info.origin_coin.name()
        assert bytes.fromhex(val["coin_name"])
        assert bytes.fromhex(val["newpuzhash"])
        assert bytes.fromhex(val["pubkey"])

        filename = "test.attest"
        val = await client.did_create_attest(
            did_wallet_2.wallet_id, val["coin_name"], val["pubkey"], val["newpuzhash"], filename
        )
        if "success" in val:
            assert val["success"]
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        val = await client.did_recovery_spend(did_wallet_id_3, [filename])
        if "success" in val:
            assert val["success"]
        for i in range(0, num_blocks * 2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        val = await client.get_wallet_balance(did_wallet_id_3)

        assert val["confirmed_wallet_balance"] == 101
        await rpc_server_cleanup()
