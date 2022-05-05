import asyncio

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from tests.time_out_assert import time_out_assert


class TestDIDRPC:
    @pytest.mark.asyncio
    async def test_did_get_set_wallet_name(self, wallet_node_simulator):
        num_blocks = 5
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()
        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for _ in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
        api_0 = WalletRpcApi(wallet_node_0)
        val = await api_0.create_new_wallet(
            {"wallet_type": "did_wallet", "did_type": "new", "backup_dids": [], "amount": 1}
        )
        await asyncio.sleep(2)
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]
        did_wallet_id = val["wallet_id"]
        val = await api_0.did_get_wallet_name({"wallet_id": did_wallet_id})
        assert val["success"]
        assert val["name"] == "Profile 1"
        new_wallet_name = "test name"
        val = await api_0.did_set_wallet_name({"wallet_id": did_wallet_id, "name": new_wallet_name})
        assert val["success"]
        val = await api_0.did_get_wallet_name({"wallet_id": did_wallet_id})
        assert val["success"]
        assert val["name"] == new_wallet_name
        val = await api_0.did_set_wallet_name({"wallet_id": wallet_0.id(), "name": new_wallet_name})
        assert val == {"success": False, "error": "Wallet id 1 is not a DID wallet"}
