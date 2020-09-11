import asyncio
import pytest

from src.rpc.wallet_rpc_api import WalletRpcApi
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.coin import Coin
from src.types.peer_info import PeerInfo
from src.util.chech32 import encode_puzzle_hash
from src.util.ints import uint16
from src.wallet.util.wallet_types import WalletType
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCCWallet:
    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(
            1, 3, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.mark.asyncio
    async def test_create_rl_coin(self, three_wallet_nodes):
        num_blocks = 4
        full_nodes, wallets = three_wallet_nodes
        full_node, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_node_2, wallet_server_2 = wallets[2]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await wallet_server_1.start_client(
            PeerInfo("localhost", uint16(server_1._port)), None
        )
        await wallet_server_2.start_client(
            PeerInfo("localhost", uint16(server_1._port)), None
        )
        await full_node.farm_new_block(FarmNewBlockProtocol(ph))
        for i in range(0, num_blocks + 1):
            await full_node.farm_new_block(FarmNewBlockProtocol(32 * b"\0"))
        fund_owners_initial_balance = await wallet.get_confirmed_balance()

        api_user = WalletRpcApi(wallet_node_1)
        val = await api_user.create_new_wallet(
            {"wallet_type": "rl_wallet", "rl_type": "user", "host": "127.0.0.1:5000"}
        )
        assert isinstance(val, dict)
        assert val["success"]
        assert val["id"]
        assert val["type"] == WalletType.RATE_LIMITED.value
        user_wallet_id = val["id"]
        pubkey = val["pubkey"]

        api_admin = WalletRpcApi(wallet_node)
        val = await api_admin.create_new_wallet(
            {
                "wallet_type": "rl_wallet",
                "rl_type": "admin",
                "interval": 2,
                "limit": 1,
                "pubkey": pubkey,
                "amount": 100,
                "host": "127.0.0.1:5000",
            }
        )
        assert isinstance(val, dict)
        assert val["success"]
        assert val["id"]
        assert val["type"] == WalletType.RATE_LIMITED.value
        assert val["origin"]
        assert val["pubkey"]
        admin_wallet_id = val["id"]
        admin_pubkey = val["pubkey"]
        origin: Coin = val["origin"]

        val = await api_user.rl_set_user_info(
            {
                "wallet_id": user_wallet_id,
                "interval": 2,
                "limit": 1,
                "origin": {
                    "parent_coin_info": origin.parent_coin_info.hex(),
                    "puzzle_hash": origin.puzzle_hash.hex(),
                    "amount": origin.amount,
                },
                "admin_pubkey": admin_pubkey,
            }
        )
        assert val["success"]

        assert (await api_user.get_wallet_balance({"wallet_id": user_wallet_id}))[
            "wallet_balance"
        ]["confirmed_wallet_balance"] == 0
        for i in range(0, 2 * num_blocks):
            await full_node.farm_new_block(FarmNewBlockProtocol(32 * b"\0"))

        async def check_balance(api, wallet_id):
            balance_response = await api.get_wallet_balance({"wallet_id": wallet_id})
            balance = balance_response["wallet_balance"]["confirmed_wallet_balance"]
            return balance

        await time_out_assert(15, check_balance, 100, api_user, user_wallet_id)
        receiving_wallet = wallet_node_2.wallet_state_manager.main_wallet
        puzzle_hash = encode_puzzle_hash(await receiving_wallet.get_new_puzzlehash())
        assert await receiving_wallet.get_spendable_balance() == 0
        val = await api_user.send_transaction(
            {
                "wallet_id": user_wallet_id,
                "amount": 3,
                "fee": 0,
                "puzzle_hash": puzzle_hash,
            }
        )

        assert val["status"] == "SUCCESS"
        for i in range(0, num_blocks):
            await full_node.farm_new_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, check_balance, 97, api_user, user_wallet_id)
        await time_out_assert(15, receiving_wallet.get_spendable_balance, 3)

        val = await api_admin.send_clawback_transaction({"wallet_id": admin_wallet_id})
        assert val["status"] == "SUCCESS"
        for i in range(0, num_blocks):
            await full_node.farm_new_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, check_balance, 0, api_admin, admin_wallet_id)
        await time_out_assert(15, check_balance, 0, api_user, user_wallet_id)
        final_balance = await wallet.get_confirmed_balance()
        assert final_balance == fund_owners_initial_balance - 3
