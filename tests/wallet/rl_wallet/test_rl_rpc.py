import asyncio

import pytest
import pytest_asyncio

from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from tests.wallet.sync.test_wallet_sync import wallet_height_at_least


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


async def is_transaction_in_mempool(user_wallet_id, api, tx_id: bytes32) -> bool:
    try:
        val = await api.get_transaction({"wallet_id": user_wallet_id, "transaction_id": tx_id.hex()})
    except ValueError:
        return False
    for _, mis, _ in TransactionRecord.from_json_dict_convenience(val["transaction"]).sent_to:
        if (
            MempoolInclusionStatus(mis) == MempoolInclusionStatus.SUCCESS
            or MempoolInclusionStatus(mis) == MempoolInclusionStatus.PENDING
        ):
            return True
    return False


async def is_transaction_confirmed(user_wallet_id, api, tx_id: bytes32) -> bool:
    try:
        val = await api.get_transaction({"wallet_id": user_wallet_id, "transaction_id": tx_id.hex()})
    except ValueError:
        return False
    return TransactionRecord.from_json_dict_convenience(val["transaction"]).confirmed


async def check_balance(api, wallet_id):
    balance_response = await api.get_wallet_balance({"wallet_id": wallet_id})
    balance = balance_response["wallet_balance"]["confirmed_wallet_balance"]
    return balance


@pytest_asyncio.fixture(scope="function")
async def three_wallet_nodes():
    async for _ in setup_simulators_and_wallets(1, 3, {}):
        yield _


class TestRLWallet:
    @pytest.mark.asyncio
    @pytest.mark.skip
    async def test_create_rl_coin(self, three_wallet_nodes, self_hostname):
        num_blocks = 4
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_node_2, wallet_server_2 = wallets[2]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        for i in range(0, num_blocks + 1):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node, 6)
        fund_owners_initial_balance = await wallet.get_confirmed_balance()
        api_user = WalletRpcApi(wallet_node_1)
        val = await api_user.create_new_wallet(
            {"wallet_type": "rl_wallet", "rl_type": "user", "host": f"{self_hostname}:5000"}
        )
        await asyncio.sleep(2)
        assert isinstance(val, dict)
        if "success" in val:
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
                "limit": 10,
                "pubkey": pubkey,
                "amount": 100,
                "fee": 1,
                "host": f"{self_hostname}:5000",
            }
        )
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]
        assert val["id"]
        assert val["type"] == WalletType.RATE_LIMITED.value
        assert val["origin"]
        assert val["pubkey"]
        admin_wallet_id = val["id"]
        admin_pubkey = val["pubkey"]
        origin: Coin = val["origin"]
        await asyncio.sleep(2)

        await api_user.rl_set_user_info(
            {
                "wallet_id": user_wallet_id,
                "interval": 2,
                "limit": 10,
                "origin": {
                    "parent_coin_info": origin.parent_coin_info.hex(),
                    "puzzle_hash": origin.puzzle_hash.hex(),
                    "amount": origin.amount,
                },
                "admin_pubkey": admin_pubkey,
            }
        )
        await asyncio.sleep(2)

        assert (await api_user.get_wallet_balance({"wallet_id": user_wallet_id}))["wallet_balance"][
            "confirmed_wallet_balance"
        ] == 0
        for i in range(0, 2 * num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node, 14)
        assert await wallet.get_confirmed_balance() == fund_owners_initial_balance - 101
        assert await check_balance(api_user, user_wallet_id) == 100
        receiving_wallet = wallet_node_2.wallet_state_manager.main_wallet
        address = encode_puzzle_hash(await receiving_wallet.get_new_puzzlehash(), "xch")
        assert await receiving_wallet.get_spendable_balance() == 0
        val = await api_user.send_transaction({"wallet_id": user_wallet_id, "amount": 3, "fee": 2, "address": address})
        await asyncio.sleep(2)
        assert "transaction_id" in val
        await time_out_assert(15, is_transaction_in_mempool, True, user_wallet_id, api_user, val["transaction_id"])
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node, 18)
        assert await is_transaction_confirmed(user_wallet_id, api_user, val["transaction_id"])
        assert await check_balance(api_user, user_wallet_id) == 95
        assert await receiving_wallet.get_spendable_balance() == 3

        val = await api_admin.add_rate_limited_funds({"wallet_id": admin_wallet_id, "amount": 100, "fee": 7})
        assert val["status"] == "SUCCESS"
        await asyncio.sleep(2)
        for i in range(0, 50):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node, 68)
        assert await check_balance(api_user, user_wallet_id) == 195
        # test spending
        puzzle_hash = encode_puzzle_hash(await receiving_wallet.get_new_puzzlehash(), "xch")
        val = await api_user.send_transaction(
            {"wallet_id": user_wallet_id, "amount": 105, "fee": 0, "address": puzzle_hash}
        )
        await asyncio.sleep(2)
        await time_out_assert(15, is_transaction_in_mempool, True, user_wallet_id, api_user, val["transaction_id"])
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node, 72)
        assert await is_transaction_confirmed(user_wallet_id, api_user, val["transaction_id"])
        assert await check_balance(api_user, user_wallet_id) == 90
        assert await receiving_wallet.get_spendable_balance() == 108

        val = await api_admin.send_clawback_transaction({"wallet_id": admin_wallet_id, "fee": 11})
        await asyncio.sleep(2)
        await time_out_assert(15, is_transaction_in_mempool, True, user_wallet_id, api_admin, val["transaction_id"])
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node, 76)
        assert await is_transaction_confirmed(user_wallet_id, api_admin, val["transaction_id"])
        assert await check_balance(api_user, user_wallet_id) == 0
        final_balance = await wallet.get_confirmed_balance()
        assert final_balance == fund_owners_initial_balance - 129
