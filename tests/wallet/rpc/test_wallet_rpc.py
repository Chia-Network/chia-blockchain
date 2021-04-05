import asyncio
import logging
from pathlib import Path

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16, uint32
from tests.setup_nodes import bt, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert

log = logging.getLogger(__name__)


class TestWalletRpc:
    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_make_transaction(self, two_wallet_nodes):
        test_rpc_port = uint16(21529)
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        ph_2 = await wallet_2.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        initial_funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        initial_funds_eventually = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        wallet_rpc_api = WalletRpcApi(wallet_node)

        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]

        def stop_node_cb():
            pass

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

        await time_out_assert(5, wallet.get_confirmed_balance, initial_funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, initial_funds)

        client = await WalletRpcClient.create("localhost", test_rpc_port, bt.root_path, config)
        try:
            addr = encode_puzzle_hash(await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(), "xch")
            tx_amount = 15600000
            try:
                await client.send_transaction("1", 100000000000000001, addr)
                raise Exception("Should not create high value tx")
            except ValueError:
                pass

            tx = await client.send_transaction("1", tx_amount, addr)
            transaction_id = tx.name

            async def tx_in_mempool():
                tx = await client.get_transaction("1", transaction_id)
                return tx.is_in_mempool()

            await time_out_assert(5, tx_in_mempool, True)
            await time_out_assert(5, wallet.get_unconfirmed_balance, initial_funds - tx_amount)
            assert (await client.get_wallet_balance("1"))["unconfirmed_wallet_balance"] == initial_funds - tx_amount
            assert (await client.get_wallet_balance("1"))["confirmed_wallet_balance"] == initial_funds

            for i in range(0, 5):
                await client.farm_block(encode_puzzle_hash(ph_2, "xch"))
                await asyncio.sleep(1)

            async def eventual_balance():
                return (await client.get_wallet_balance("1"))["confirmed_wallet_balance"]

            await time_out_assert(5, eventual_balance, initial_funds_eventually - tx_amount)

            address = await client.get_next_address("1", True)
            assert len(address) > 10

            transactions = await client.get_transactions("1")
            assert len(transactions) > 1

            pks = await client.get_public_keys()
            assert len(pks) == 1

            assert (await client.get_height_info()) > 0

            sk_dict = await client.get_private_key(pks[0])
            assert sk_dict["fingerprint"] == pks[0]
            assert sk_dict["sk"] is not None
            assert sk_dict["pk"] is not None
            assert sk_dict["seed"] is not None

            mnemonic = await client.generate_mnemonic()
            assert len(mnemonic) == 24

            await client.add_key(mnemonic)

            pks = await client.get_public_keys()
            assert len(pks) == 2

            await client.log_in_and_skip(pks[1])
            sk_dict = await client.get_private_key(pks[1])
            assert sk_dict["fingerprint"] == pks[1]

            await client.delete_key(pks[0])
            await client.log_in_and_skip(pks[1])
            assert len(await client.get_public_keys()) == 1

            assert not (await client.get_sync_status())

            wallets = await client.get_wallets()
            assert len(wallets) == 1
            balance = await client.get_wallet_balance(wallets[0]["id"])
            assert balance["unconfirmed_wallet_balance"] == 0

            test_wallet_backup_path = Path("test_wallet_backup_file")
            await client.create_backup(test_wallet_backup_path)
            assert test_wallet_backup_path.exists()
            test_wallet_backup_path.unlink()

            try:
                await client.send_transaction(wallets[0]["id"], 100, addr)
                raise Exception("Should not create tx if no balance")
            except ValueError:
                pass

            await client.delete_all_keys()

            assert len(await client.get_public_keys()) == 0
        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            await client.await_closed()
            await rpc_cleanup()
