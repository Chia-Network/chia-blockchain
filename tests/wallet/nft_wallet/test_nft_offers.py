import asyncio
from secrets import token_bytes
from typing import Any, Dict, Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import create_asset_id, match_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from tests.time_out_assert import time_out_assert, time_out_assert_not_none


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32) -> bool:
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


async def get_trade_and_status(trade_manager, trade) -> TradeStatus:  # type: ignore
    trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
    return TradeStatus(trade_rec.status)


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_offer_with_fee(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_maker = wallet_node_0.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_1.wallet_state_manager.main_wallet

    maker_ph = await wallet_maker.get_new_puzzlehash()
    taker_ph = await wallet_taker.get_new_puzzlehash()
    token_ph = bytes32(token_bytes())

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
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(10, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, funds)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    )

    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(metadata)
    assert sb
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 1
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_taker) == 0

    # MAKE FIRST TRADE: 1 NFT for 100 xch
    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_xch, driver_dict, fee=maker_fee
    )
    await asyncio.sleep(1)
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)
    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), fee=taker_fee
    )

    await asyncio.sleep(1)
    assert success
    assert error is None
    assert trade_take is not None

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await asyncio.sleep(5)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, maker_balance_pre + xch_request - maker_fee)
    await time_out_assert(10, wallet_taker.get_confirmed_balance, taker_balance_pre - xch_request - taker_fee)

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 0
    assert len(coins_taker) == 1

    # MAKE SECOND TRADE: 100 xch for 1 NFT

    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_buy = coins_taker[0]
    nft_to_buy_info: Optional[PuzzleInfo] = match_puzzle(nft_to_buy.full_puzzle)
    nft_to_buy_asset_id: bytes32 = create_asset_id(nft_to_buy_info)  # type: ignore
    driver_dict_to_buy: Dict[bytes32, Optional[PuzzleInfo]] = {nft_to_buy_asset_id: nft_to_buy_info}

    xch_offered = 100
    maker_fee = uint64(10)
    offer_xch_for_nft = {wallet_maker.id(): -xch_offered, nft_to_buy_asset_id: 1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_xch_for_nft, driver_dict_to_buy, fee=maker_fee
    )
    await asyncio.sleep(1)
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)
    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), fee=taker_fee
    )

    await asyncio.sleep(1)
    assert success
    assert error is None
    assert trade_take is not None

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await asyncio.sleep(5)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, maker_balance_pre - xch_offered - maker_fee)
    await time_out_assert(10, wallet_taker.get_confirmed_balance, taker_balance_pre + xch_offered - taker_fee)

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 1
    assert len(coins_taker) == 0


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_offer_cancellations(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_maker = wallet_node_0.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_1.wallet_state_manager.main_wallet

    maker_ph = await wallet_maker.get_new_puzzlehash()
    taker_ph = await wallet_taker.get_new_puzzlehash()
    token_ph = bytes32(token_bytes())

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
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(10, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, funds)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    )

    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    # trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(metadata)
    assert sb
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 1
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_taker) == 0

    # maker creates offer and cancels
    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    # taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_xch, driver_dict, fee=maker_fee
    )
    await asyncio.sleep(1)
    assert success is True
    assert error is None
    assert trade_make is not None

    # await trade_manager_maker.cancel_pending_offer(trade_make.trade_id)
    # await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    cancel_fee = uint64(10)

    txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=cancel_fee)

    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    for tx in txs:
        if tx.spend_bundle is not None:
            await time_out_assert(15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx.spend_bundle.name())

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    maker_balance = await wallet_maker.get_confirmed_balance()
    assert maker_balance == maker_balance_pre - cancel_fee
    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 1


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_offer_with_metadata_update(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_maker = wallet_node_0.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_1.wallet_state_manager.main_wallet

    maker_ph = await wallet_maker.get_new_puzzlehash()
    taker_ph = await wallet_taker.get_new_puzzlehash()
    token_ph = bytes32(token_bytes())

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
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(10, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, funds)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    )

    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(metadata)
    assert sb
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 1
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_taker) == 0

    # Maker updates metadata:
    nft_to_update = coins_maker[0]
    url_to_add = "https://new_url.com"
    fee_for_update = uint64(10)
    update_sb = await nft_wallet_maker.update_metadata(nft_to_update, url_to_add, fee=fee_for_update)
    mempool_mgr = full_node_api.full_node.mempool_manager
    await time_out_assert_not_none(5, mempool_mgr.get_spendbundle, update_sb.name())  # type: ignore

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    updated_nft = coins_maker[0]
    updated_nft_info = match_puzzle(updated_nft.full_puzzle)
    assert url_to_add in updated_nft_info.also().info["metadata"]  # type: ignore

    # MAKE FIRST TRADE: 1 NFT for 100 xch
    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_xch, driver_dict, fee=maker_fee
    )
    await asyncio.sleep(1)
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)
    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), fee=taker_fee
    )

    await asyncio.sleep(1)
    assert success
    assert error is None
    assert trade_take is not None

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await asyncio.sleep(5)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, maker_balance_pre + xch_request - maker_fee)
    await time_out_assert(10, wallet_taker.get_confirmed_balance, taker_balance_pre - xch_request - taker_fee)

    coins_maker = nft_wallet_maker.nft_wallet_info.my_nft_coins
    coins_taker = nft_wallet_taker.nft_wallet_info.my_nft_coins
    assert len(coins_maker) == 0
    assert len(coins_taker) == 1
