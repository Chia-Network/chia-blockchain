import asyncio

import pytest

from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16, uint32
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert, time_out_assert_not_none
# from tests.wallet.sync.test_wallet_sync import wallet_height_at_least
from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash


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


class TestNFTRPC:
    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.mark.parametrize(
        "trusted",
        [True],
    )
    @pytest.mark.asyncio
    async def test_create_nft_coin(self, three_wallet_nodes, trusted):
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
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
        await time_out_assert(15, wallet_1.get_unconfirmed_balance, funds)
        await time_out_assert(15, wallet_1.get_confirmed_balance, funds)

        # await time_out_assert(15, wallet_height_at_least, True, wallet_node, 6)
        api_0 = WalletRpcApi(wallet_node_0)
        val = await api_0.create_new_wallet(
            {"wallet_type": "did_wallet", "did_type": "new", "backup_dids": [], "amount": 11}
        )
        await asyncio.sleep(2)
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]
        assert val["my_did"]
        assert val["type"] == WalletType.DISTRIBUTED_ID.value
        did_0 = val["my_did"]
        did_wallet_id_0 = val["wallet_id"]

        api_1 = WalletRpcApi(wallet_node_1)

        val = await api_1.create_new_wallet(
            {"wallet_type": "did_wallet", "did_type": "new", "backup_dids": [], "amount": 21}
        )
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]
        assert val["my_did"]
        assert val["type"] == WalletType.DISTRIBUTED_ID.value
        did_1 = val["my_did"]
        did_wallet_id_1 = val["wallet_id"]
        await asyncio.sleep(2)

        val = await api_0.create_new_wallet(
            {"wallet_type": "nft_wallet", "did_wallet_id": did_wallet_id_0}
        )
        assert val["success"]
        nft_wallet_id_0 = val["wallet_id"]
        val = await api_1.create_new_wallet(
            {"wallet_type": "nft_wallet", "did_wallet_id": did_wallet_id_1}
        )
        assert val["success"]
        nft_wallet_id_1 = val["wallet_id"]

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(3)

        # metadata = Program.to([
        #     ('u', ["https://www.chia.net/img/branding/chia-logo.svg"]),
        #     ('h', 0xd4584ad463139fa8c0d9f68f4b59f185),
        # ])
        val = await api_0.nft_mint_nft(
            {
                "wallet_id": nft_wallet_id_0,
                "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
                "hash": 0xd4584ad463139fa8c0d9f68f4b59f185,
                "artist_percentage": 20,
                "artist_address": ph2
            }
        )

        assert val["success"]

        await asyncio.sleep(5)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(5)

        val = await api_0.nft_get_current_nfts({"wallet_id": nft_wallet_id_0})

        assert val["success"]
        assert len(val["nfts"]) == 1
        nft_coin_info = val["nfts"][0][0]
        assert val["nfts"][0][1] == [b"https://www.chia.net/img/branding/chia-logo.svg"]

        val = await api_1.did_get_current_coin_info({"wallet_id": did_wallet_id_0})
        assert val["success"]

        trade_price = [[50]]

        val = await api_0.nft_transfer_nft({
            "wallet_id": nft_wallet_id_0,
            "nft_coin_info": nft_coin_info,
            "new_did": did_1,
            "new_did_parent": val["did_parent"],
            "new_did_inner_hash": val["did_innerpuz"],
            "new_did_amount": val["did_amount"],
            "trade_price": trade_price
        })

        assert val["success"]
        assert val["spend_bundle"] is not None

        val = await api_1.nft_receive_nft({
            "wallet_id": nft_wallet_id_1,
            "spend_bundle": val["spend_bundle"]
        })

        assert val["success"]

        await asyncio.sleep(5)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(5)

        val = await api_1.nft_get_current_nfts({"wallet_id": nft_wallet_id_1})

        assert val["success"]
        assert len(val["nfts"]) == 1
        assert val["nfts"][0][1] == [b"https://www.chia.net/img/branding/chia-logo.svg"]
