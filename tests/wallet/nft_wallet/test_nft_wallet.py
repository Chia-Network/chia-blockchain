import asyncio
from secrets import token_bytes

# pytestmark = pytest.mark.skip("TODO: Fix tests")
from typing import Any, Dict, Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import create_asset_id, match_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.wallet_types import WalletType
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
async def test_nft_wallet_creation_automatically(two_wallet_nodes: Any, trusted: Any) -> None:
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
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_0.generate_new_nft(metadata)
    assert sb
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 1, "nft not generated"

    sb = await nft_wallet_0.transfer_nft(coins[0], ph1)
    assert sb is not None
    await asyncio.sleep(3)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    await asyncio.sleep(5)

    assert len(wallet_node_1.wallet_state_manager.wallets) == 2
    # Get the new NFT wallet
    nft_wallets = await wallet_node_1.wallet_state_manager.get_all_wallet_info_entries(WalletType.NFT)
    assert len(nft_wallets) == 1
    nft_wallet_1: NFTWallet = wallet_node_1.wallet_state_manager.wallets[nft_wallets[0].id]
    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 0
    coins = nft_wallet_1.nft_wallet_info.my_nft_coins
    assert len(coins) == 1


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_wallet_creation_and_transfer(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
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
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_0.generate_new_nft(metadata)
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 1, "nft not generated"

    metadata = Program.to(
        [
            ("u", ["https://www.test.net/logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F181"),
        ]
    )

    sb = await nft_wallet_0.generate_new_nft(metadata)
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 2, "nft not generated"

    nft_wallet_1 = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
    )
    sb = await nft_wallet_0.transfer_nft(coins[1], ph1)

    assert sb is not None
    # ensure hints are generated
    assert compute_memos(sb)

    await asyncio.sleep(3)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    await asyncio.sleep(5)

    coins = nft_wallet_0.nft_wallet_info.my_nft_coins
    assert len(coins) == 1
    coins = nft_wallet_1.nft_wallet_info.my_nft_coins
    assert len(coins) == 1

    # Send it back to original owner
    nsb = await nft_wallet_1.transfer_nft(coins[0], ph)
    assert nsb is not None

    # ensure hints are generated
    assert compute_memos(nsb)
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
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
        }
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    sb = tr1["spend_bundle"]

    await asyncio.sleep(5)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(3)
    tr2 = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F184",
            "uris": ["https://chialisp.com/img/logo.svg"],
        }
    )
    assert isinstance(tr2, dict)
    assert tr2.get("success")
    sb = tr2["spend_bundle"]
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
        uris.append(coin.to_json_dict()["data_uris"][0])
    assert len(uris) == 2
    assert "https://chialisp.com/img/logo.svg" in uris
    assert bytes32.fromhex(coins[1].to_json_dict()["nft_coin_id"]) in [x.name() for x in sb.additions()]


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
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
        }
    )

    assert resp.get("success")
    sb = resp["spend_bundle"]

    await asyncio.sleep(5)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(3)
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    coin = coins[0].to_json_dict()
    nft_coin_id = coin["nft_coin_id"]
    # add another URI
    tr1 = await api_0.nft_add_uri(
        {
            "wallet_id": nft_wallet_0_id,
            "nft_coin_id": nft_coin_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uri": "https://www.chia.net/img/branding/chia-logo-white.svg",
        }
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    sb = tr1["spend_bundle"]
    await asyncio.sleep(5)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(5)
    # check that new URI was added
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    coin = coins[0].to_json_dict()
    uris = coin["data_uris"]
    assert len(uris) == 2
    assert "https://www.chia.net/img/branding/chia-logo-white.svg" in uris


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_offer(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
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
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

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

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(metadata)
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins) == 1, "nft not generated"

    metadata = Program.to(
        [
            ("u", ["https://www.test.net/logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F181"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(metadata)
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await asyncio.sleep(5)
    coins = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins) == 2, "nft not generated"

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
    )
    sb = await nft_wallet_maker.transfer_nft(coins[1], ph1)

    assert sb is not None
    # ensure hints are generated
    assert compute_memos(sb)

    await asyncio.sleep(3)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    await asyncio.sleep(5)

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 1
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_taker) == 1

    nft_coin_info = coins_maker[0]
    nft_info_1: Optional[PuzzleInfo] = match_puzzle(nft_coin_info.full_puzzle)
    nft_asset_id_1: bytes32 = create_asset_id(nft_info_1)  # type: ignore
    driver_dict_1: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id_1: nft_info_1}

    offer_nft_for_xch = {wallet_0.id(): 100, nft_asset_id_1: -1}

    trade_manager_maker = wallet_0.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_1.wallet_state_manager.trade_manager

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(offer_nft_for_xch, driver_dict_1)
    await asyncio.sleep(1)
    assert success is True
    assert error is None
    assert trade_make is not None

    success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))

    await asyncio.sleep(1)
    assert success
    assert error is None
    assert trade_take is not None

    async def get_trade_and_status(trade_manager, trade) -> TradeStatus:  # type: ignore
        trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
        return TradeStatus(trade_rec.status)

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(5)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 0
    assert len(coins_taker) == 2

    nft_coin_info = coins_taker[0]
    nft_info_2: Optional[PuzzleInfo] = match_puzzle(nft_coin_info.full_puzzle)
    nft_asset_id_2: bytes32 = create_asset_id(nft_info_2)  # type: ignore
    driver_dict_2: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id_2: nft_info_2}

    offer_xch_for_nft = {wallet_0.id(): -100, nft_asset_id_2: 1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(offer_xch_for_nft, driver_dict_2)
    await asyncio.sleep(1)
    assert success is True
    assert error is None
    assert trade_make is not None

    success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))

    await asyncio.sleep(1)
    assert success
    assert error is None
    assert trade_take is not None

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await asyncio.sleep(5)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 1
    assert len(coins_taker) == 1


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_cat_offer(wallets_prefarm: Any, trusted: Any) -> None:
    buffer_blocks = 5
    wallet_node_maker, wallet_node_taker, full_node_api = wallets_prefarm
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    # Create two new CATs, one in each wallet
    async with wallet_node_maker.wallet_state_manager.lock:
        cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(100)
        )
        await asyncio.sleep(1)

    async with wallet_node_taker.wallet_state_manager.lock:
        new_cat_wallet_taker: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_taker.wallet_state_manager, wallet_taker, {"identifier": "genesis_by_id"}, uint64(100)
        )
        await asyncio.sleep(1)

    for i in range(1, buffer_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(token_bytes())))
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, 100)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, 100)
    await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, 100)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, 100)

    assert cat_wallet_maker.cat_info.my_tail is not None
    assert new_cat_wallet_taker.cat_info.my_tail is not None

    # add wallet for taker's cat to maker
    new_cat_wallet_maker: CATWallet = await CATWallet.create_wallet_for_cat(
        wallet_node_maker.wallet_state_manager, wallet_maker, new_cat_wallet_taker.get_asset_id()
    )

    # make nft wallets
    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    # nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
    #     wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    # )

    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    ph_maker = await wallet_maker.get_new_puzzlehash()
    # ph_taker = await wallet_taker.get_new_puzzlehash()

    sb = await nft_wallet_maker.generate_new_nft(metadata)
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, buffer_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))

    await asyncio.sleep(5)
    coins = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins) == 1, "nft not generated"

    nft_coin_info = coins[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(nft_coin_info.full_puzzle)
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    nft_for_cat = {nft_asset_id: -1, new_cat_wallet_maker.id(): 10}

    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(nft_for_cat, driver_dict)
    await asyncio.sleep(1)
    assert success is True
    assert error is None
    assert trade_make is not None

    success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))

    await asyncio.sleep(1)
    assert success
    assert error is None
    assert trade_take is not None

    async def get_trade_and_status(trade_manager, trade) -> TradeStatus:  # type: ignore
        trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
        return TradeStatus(trade_rec.status)

    for i in range(1, buffer_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await asyncio.sleep(5)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
