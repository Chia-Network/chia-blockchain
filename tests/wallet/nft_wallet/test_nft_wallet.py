import asyncio

# pytestmark = pytest.mark.skip("TODO: Fix tests")
from typing import Any

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from tests.time_out_assert import time_out_assert, time_out_assert_not_none


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32) -> bool:
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_wallet_creation_and_transfer(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await time_out_assert(15, wallet_0.get_pending_change_balance, 0)
    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
        ]
    )

    tr = await nft_wallet_0.generate_new_nft(metadata)
    assert tr
    assert tr.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, tr.spend_bundle.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 1, "nft not generated"

    metadata = Program.to(
        [
            ("u", ["https://www.test.net/logo.svg"]),
            ("h", 0xD4584AD463139FA8C0D9F68F4B59F181),
        ]
    )

    tr = await nft_wallet_0.generate_new_nft(metadata)
    assert tr
    assert tr.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, tr.spend_bundle.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 2, "nft not generated"

    nft_wallet_1 = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
    )
    sb = await nft_wallet_0.transfer_nft(coins[0], ph1)

    assert sb is not None
    await asyncio.sleep(3)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    await asyncio.sleep(5)

    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 1
    coins = nft_wallet_1.nft_wallet_info.my_nft_coins
    assert len(coins) == 1

    # Send it back to original owner
    nsb = await nft_wallet_1.transfer_nft(coins[0], ph)
    assert sb is not None

    # full_sb = await nft_wallet_0.receive_nft(nsb)
    # await nft_wallet_0.receive_nft(nsb)
    assert nsb is not None
    await asyncio.sleep(5)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 2

    coins = nft_wallet_1.nft_wallet_info.my_nft_coins
    assert len(coins) == 0


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_wallet_rpc_creation_and_list(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph = await wallet_0.get_new_puzzlehash()
    _ = await wallet_1.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    api_0 = WalletRpcApi(wallet_node_0)
    nft_wallet_0 = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1"))
    assert isinstance(nft_wallet_0, dict)
    assert nft_wallet_0.get("success")
    nft_wallet_0_id = nft_wallet_0["wallet_id"]

    tr1 = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": 0xD4584AD463139FA8C0D9F68F4B59F185,
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg", "hehe"],
        }
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    sb = tr1["nft"].spend_bundle

    await asyncio.sleep(5)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(3)
    tr2 = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": 0xD4584AD463139FA8C0D9F68F4B59F184,
            "uris": ["https://chialisp.com/img/logo.svg", "hehe2"],
        }
    )
    assert isinstance(tr2, dict)
    assert tr2.get("success")
    sb = tr2["nft"].spend_bundle
    await asyncio.sleep(5)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(3)
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    assert len(coins) == 2
    uris = []
    for coin in coins:
        uris.append(coin["data_uris"][0])
    print(uris)
    assert len(uris) == 2
    assert "https://chialisp.com/img/logo.svg" in uris
    assert coins[1]["nft_coin_id"] in [x.name().hex() for x in sb.additions()]


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_wallet_rpc_update_metadata(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph = await wallet_0.get_new_puzzlehash()
    _ = await wallet_1.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    api_0 = WalletRpcApi(wallet_node_0)
    nft_wallet_0 = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1"))
    assert isinstance(nft_wallet_0, dict)
    assert nft_wallet_0.get("success")
    nft_wallet_0_id = nft_wallet_0["wallet_id"]

    # mint NFT
    tr1 = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": 0xD4584AD463139FA8C0D9F68F4B59F185,
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
        }
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    sb = tr1["nft"].spend_bundle

    await asyncio.sleep(5)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(3)
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    nft_coin_id = coins[0]["nft_coin_id"]
    # add another URI
    tr1 = await api_0.nft_add_uri(
        {
            "wallet_id": nft_wallet_0_id,
            "nft_coin_id": nft_coin_id,
            "hash": 0xD4584AD463139FA8C0D9F68F4B59F185,
            "uri": "https://www.chia.net/img/branding/chia-logo-white.svg",
        }
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    sb = tr1["nft"].spend_bundle

    await asyncio.sleep(5)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(3)

    # check that new URI was added
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    assert len(coins) == 2
    uris = []
    for coin in coins:
        uris.append(coin["data_uris"][0])
    print(uris)
    assert len(uris) == 2
    assert "https://www.chia.net/img/branding/chia-logo-white.svg" in uris
