import asyncio
import json
from typing import List

import pytest
from blspy import PrivateKey

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.minter.did_mint import DIDMintingTool
from chia.minter.nft_mint import NFTMintingTool
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_server import start_rpc_server
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16, uint32
from tests.time_out_assert import time_out_assert

# pytestmark = pytest.mark.skip("TODO: Fix tests")
from tests.util.socket import find_available_listen_port


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


class TestNFTMinting:
    @pytest.mark.parametrize(
        "trusted",
        [True],
    )
    @pytest.mark.asyncio
    async def test_mining_tool(self, three_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet_node_2, server_2 = wallets[2]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()
        ph1 = await wallet_1.get_new_puzzlehash()
        ph2 = await wallet_2.get_new_puzzlehash()
        full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

        def stop_node_cb():
            full_node_api._close()
            full_node_server.close_all()

        test_rpc_port = find_available_listen_port()
        test_daemon_port = find_available_listen_port()
        config = full_node_api.bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]
        rpc_cleanup = await start_rpc_server(
            full_node_rpc_api,
            "localhost",
            test_daemon_port,
            test_rpc_port,
            stop_node_cb,
            full_node_api.bt.root_path,
            config,
            connect_to_daemon=False,
        )

        rpc_client = await FullNodeRpcClient.create("localhost", test_rpc_port, full_node_api.bt.root_path, config)

        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_1.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )
        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)

        # Minting tool
        # key_bytes = hexstr_to_bytes("3dcbd044d3aefe0ac58202f974294ea59d5c56d6ca258450a9639f66a615aa38")
        private_key = PrivateKey.from_bytes(32 * b"\0")
        minting_tool = DIDMintingTool(private_key, wallet_node_0.constants)
        puzzle_hash = await minting_tool.get_new_p2_inner_hash()

        # Send a coin to a minting address

        tx_record = await wallet_0.generate_signed_transaction(1, puzzle_hash, 0)
        await wallet_0.push_transaction(tx_record)

        await time_out_assert(
            15,
            tx_in_pool,
            True,
            full_node_api.full_node.mempool_manager,
            tx_record.spend_bundle.name(),
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        coin_records = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(True, puzzle_hash)
        assert len(coin_records) == 1
        origin = coin_records[0].coin

        did_creation: SpendBundle = await minting_tool.create_did_coin(origin, origin.amount)
        push_response = await rpc_client.push_tx(did_creation)
        assert push_response["status"] == "SUCCESS"
        assert push_response["success"] == True

        await time_out_assert(
            15,
            tx_in_pool,
            True,
            full_node_api.full_node.mempool_manager,
            did_creation.name(),
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        coin_ids = [coin.name() for coin in did_creation.additions()]
        coin_states = await full_node_api.full_node.coin_store.get_coin_states_by_ids(True, coin_ids)
        assert len(coin_records) == len(did_creation.additions())

        did_coin = None
        for state in coin_states:
            if state.coin.amount == 1 and state.spent_height is None:
                did_coin = state.coin
                break

        assert did_coin is not None
        nft_minting_tool = NFTMintingTool(private_key, wallet_node_0.constants, minting_tool.did_info)

        launcher_bundle = nft_minting_tool
        breakpoint()
        print("coin_records")
