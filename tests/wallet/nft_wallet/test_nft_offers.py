from __future__ import annotations

from secrets import token_bytes
from typing import Any, Dict, Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
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
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.debug_spend_bundle import disassemble
from tests.wallet.nft_wallet.test_nft_1_offers import mempool_not_empty


async def get_trade_and_status(trade_manager, trade) -> TradeStatus:  # type: ignore
    trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
    return TradeStatus(trade_rec.status)


@pytest.mark.parametrize(
    "trusted",
    [False],
)
@pytest.mark.parametrize(
    "reuse_puzhash",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_offer_with_fee(self_hostname: str, two_wallet_nodes: Any, trusted: Any, reuse_puzhash: bool) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
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

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))

    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

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
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1

    assert await nft_wallet_taker.get_nft_count() == 0
    # MAKE FIRST TRADE: 1 NFT for 100 xch
    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch = {wallet_maker.id(): xch_request, nft_asset_id: -1}
    maker_unused_index = (
        await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index
    taker_unused_index = (
        await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_xch, driver_dict, fee=maker_fee, reuse_puzhash=reuse_puzhash
    )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    peer = wallet_node_1.get_full_node_peer()
    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
        fee=taker_fee,
        reuse_puzhash=reuse_puzhash,
    )
    assert trade_take is not None
    assert tx_records is not None

    await full_node_api.process_transaction_records(records=tx_records)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, maker_balance_pre + xch_request - maker_fee)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, taker_balance_pre - xch_request - taker_fee)
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1

    assert await nft_wallet_maker.get_nft_count() == 0
    if reuse_puzhash:
        # Check if unused index changed
        assert (
            maker_unused_index
            == (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            == (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
    else:
        assert (
            maker_unused_index
            < (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            < (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
    # MAKE SECOND TRADE: 100 xch for 1 NFT

    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_buy = coins_taker[0]
    nft_to_buy_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_buy.full_puzzle))
    nft_to_buy_asset_id: bytes32 = create_asset_id(nft_to_buy_info)  # type: ignore
    driver_dict_to_buy: Dict[bytes32, Optional[PuzzleInfo]] = {nft_to_buy_asset_id: nft_to_buy_info}

    xch_offered = 1000
    maker_fee = uint64(10)
    offer_xch_for_nft = {wallet_maker.id(): -xch_offered, nft_to_buy_asset_id: 1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_xch_for_nft, driver_dict_to_buy, fee=maker_fee
    )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=taker_fee
    )

    assert trade_take is not None
    assert tx_records is not None

    await full_node_api.process_transaction_records(records=tx_records)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, maker_balance_pre - xch_offered - maker_fee)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, taker_balance_pre + xch_offered - taker_fee)

    assert await nft_wallet_maker.get_nft_count() == 1
    assert await nft_wallet_taker.get_nft_count() == 0


@pytest.mark.parametrize(
    "trusted",
    [False],
)
@pytest.mark.asyncio
async def test_nft_offer_cancellations(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
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

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

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
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    assert await nft_wallet_taker.get_nft_count() == 0
    # maker creates offer and cancels
    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    # taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_xch, driver_dict, fee=maker_fee
    )
    assert success is True
    assert error is None
    assert trade_make is not None

    # await trade_manager_maker.cancel_pending_offer(trade_make.trade_id)
    # await time_out_assert(20, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    cancel_fee = uint64(10)

    txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=cancel_fee)

    await time_out_assert(20, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    await full_node_api.process_transaction_records(records=txs)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    maker_balance = await wallet_maker.get_confirmed_balance()
    assert maker_balance == maker_balance_pre - cancel_fee
    assert await nft_wallet_maker.get_nft_count() == 1


@pytest.mark.parametrize(
    "trusted",
    [False],
)
@pytest.mark.asyncio
async def test_nft_offer_with_metadata_update(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
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

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

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
            ("mu", []),
            ("lu", []),
            ("sn", uint64(1)),
            ("st", uint64(1)),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(metadata)
    assert sb
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    assert await nft_wallet_taker.get_nft_count() == 0

    # Maker updates metadata:
    nft_to_update = coins_maker[0]
    url_to_add = "https://new_url.com"
    key = "mu"
    fee_for_update = uint64(10)
    update_sb = await nft_wallet_maker.update_metadata(nft_to_update, key, url_to_add, fee=fee_for_update)
    mempool_mgr = full_node_api.full_node.mempool_manager
    await time_out_assert_not_none(20, mempool_mgr.get_spendbundle, update_sb.name())  # type: ignore

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    coins_maker = await nft_wallet_maker.get_current_nfts()
    updated_nft = coins_maker[0]
    updated_nft_info = match_puzzle(uncurry_puzzle(updated_nft.full_puzzle))

    assert url_to_add in disassemble(updated_nft_info.also().info["metadata"])  # type: ignore

    # MAKE FIRST TRADE: 1 NFT for 100 xch
    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_xch, driver_dict, fee=maker_fee
    )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    peer = wallet_node_1.get_full_node_peer()
    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=taker_fee
    )

    assert trade_take is not None
    assert tx_records is not None

    await full_node_api.process_transaction_records(records=tx_records)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, maker_balance_pre + xch_request - maker_fee)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, taker_balance_pre - xch_request - taker_fee)

    assert await nft_wallet_maker.get_nft_count() == 0
    assert await nft_wallet_taker.get_nft_count() == 1


@pytest.mark.parametrize(
    "trusted",
    [False],
)
@pytest.mark.parametrize(
    "reuse_puzhash",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_offer_nft_for_cat(
    self_hostname: str,
    two_wallet_nodes: Any,
    trusted: Any,
    reuse_puzhash: bool,
) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
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

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    # Create NFT wallets and nfts for maker and taker
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
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    assert await nft_wallet_taker.get_nft_count() == 0
    # Create two new CATs and wallets for maker and taker
    cats_to_mint = 10000
    async with wallet_node_0.wallet_state_manager.lock:
        cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_0.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(cats_to_mint)
        )
        await time_out_assert(20, mempool_not_empty, True, full_node_api)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    async with wallet_node_1.wallet_state_manager.lock:
        cat_wallet_taker: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_1.wallet_state_manager, wallet_taker, {"identifier": "genesis_by_id"}, uint64(cats_to_mint)
        )
        await time_out_assert(20, mempool_not_empty, True, full_node_api)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, cat_wallet_maker.get_confirmed_balance, cats_to_mint)
    await time_out_assert(20, cat_wallet_maker.get_unconfirmed_balance, cats_to_mint)
    await time_out_assert(20, cat_wallet_taker.get_confirmed_balance, cats_to_mint)
    await time_out_assert(20, cat_wallet_taker.get_unconfirmed_balance, cats_to_mint)

    wallet_maker_for_taker_cat: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
        wallet_node_0.wallet_state_manager, wallet_maker, cat_wallet_taker.get_asset_id()
    )

    wallet_taker_for_maker_cat: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
        wallet_node_1.wallet_state_manager, wallet_taker, cat_wallet_maker.get_asset_id()
    )

    assert wallet_taker_for_maker_cat
    # MAKE FIRST TRADE: 1 NFT for 10 taker cats
    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()
    taker_cat_maker_balance_pre = await wallet_maker_for_taker_cat.get_confirmed_balance()
    taker_cat_taker_balance_pre = await cat_wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_asset_id: bytes32 = create_asset_id(nft_info)  # type: ignore
    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {nft_asset_id: nft_info}

    maker_fee = uint64(10)
    taker_cat_offered = 2500
    offer_nft_for_cat = {nft_asset_id: -1, wallet_maker_for_taker_cat.id(): taker_cat_offered}
    maker_unused_index = (
        await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index
    taker_unused_index = (
        await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_cat, driver_dict, fee=maker_fee, reuse_puzhash=reuse_puzhash
    )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    peer = wallet_node_1.get_full_node_peer()
    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
        fee=taker_fee,
        reuse_puzhash=reuse_puzhash,
    )

    assert trade_take is not None
    assert tx_records is not None

    await full_node_api.process_transaction_records(records=tx_records)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    taker_cat_maker_balance_post = await wallet_maker_for_taker_cat.get_confirmed_balance()
    taker_cat_taker_balance_post = await cat_wallet_taker.get_confirmed_balance()
    assert taker_cat_maker_balance_post == taker_cat_maker_balance_pre + taker_cat_offered
    assert taker_cat_taker_balance_post == taker_cat_taker_balance_pre - taker_cat_offered
    maker_balance_post = await wallet_maker.get_confirmed_balance()
    taker_balance_post = await wallet_taker.get_confirmed_balance()
    assert maker_balance_post == maker_balance_pre - maker_fee
    assert taker_balance_post == taker_balance_pre - taker_fee
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1

    assert await nft_wallet_maker.get_nft_count() == 0
    if reuse_puzhash:
        # Check if unused index changed
        assert (
            maker_unused_index
            == (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            == (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
    else:
        assert (
            maker_unused_index
            < (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            < (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
    # Make an offer for taker NFT for multiple cats
    maker_cat_amount = 400
    taker_cat_amount = 500

    nft_to_buy = coins_taker[0]
    nft_to_buy_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_buy.full_puzzle))
    nft_to_buy_asset_id: bytes32 = create_asset_id(nft_to_buy_info)  # type: ignore

    driver_dict_to_buy: Dict[bytes32, Optional[PuzzleInfo]] = {
        nft_to_buy_asset_id: nft_to_buy_info,
    }

    maker_fee = uint64(10)
    offer_multi_cats_for_nft = {
        nft_to_buy_asset_id: 1,
        wallet_maker_for_taker_cat.id(): -taker_cat_amount,
        cat_wallet_maker.id(): -maker_cat_amount,
    }

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_multi_cats_for_nft, driver_dict_to_buy, fee=maker_fee
    )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=taker_fee
    )

    assert trade_take is not None
    assert tx_records is not None

    await full_node_api.process_transaction_records(records=tx_records)
    # check balances: taker wallet down an NFT, up cats
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    taker_cat_maker_balance_post_2 = await wallet_maker_for_taker_cat.get_confirmed_balance()
    taker_cat_taker_balance_post_2 = await cat_wallet_taker.get_confirmed_balance()
    assert taker_cat_maker_balance_post_2 == taker_cat_maker_balance_post - taker_cat_amount
    assert taker_cat_taker_balance_post_2 == taker_cat_taker_balance_post + taker_cat_amount
    maker_balance_post_2 = await wallet_maker.get_confirmed_balance()
    taker_balance_post_2 = await wallet_taker.get_confirmed_balance()
    assert maker_balance_post_2 == maker_balance_post - maker_fee
    assert taker_balance_post_2 == taker_balance_post - taker_fee
    assert await nft_wallet_maker.get_nft_count() == 1
    assert await nft_wallet_taker.get_nft_count() == 0


@pytest.mark.parametrize(
    "trusted",
    [False],
)
@pytest.mark.asyncio
async def test_nft_offer_nft_for_nft(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
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

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(maker_ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(taker_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    # Create NFT wallets and nfts for maker and taker
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
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    metadata_2 = Program.to(
        [
            ("u", ["https://www.chia.net/image2.html"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F183"),
        ]
    )
    sb_2 = await nft_wallet_taker.generate_new_nft(metadata_2)
    assert sb_2
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb_2.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1

    maker_balance_pre = await wallet_maker.get_confirmed_balance()
    taker_balance_pre = await wallet_taker.get_confirmed_balance()

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore

    nft_to_take = coins_taker[0]
    nft_to_take_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_take.full_puzzle))
    nft_to_take_asset_id: bytes32 = create_asset_id(nft_to_take_info)  # type: ignore

    driver_dict: Dict[bytes32, Optional[PuzzleInfo]] = {
        nft_to_offer_asset_id: nft_to_offer_info,
        nft_to_take_asset_id: nft_to_take_info,
    }

    maker_fee = uint64(10)
    offer_nft_for_nft = {nft_to_take_asset_id: 1, nft_to_offer_asset_id: -1}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_nft_for_nft, driver_dict, fee=maker_fee
    )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    peer = wallet_node_1.get_full_node_peer()
    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=taker_fee
    )

    assert trade_take is not None
    assert tx_records is not None

    await full_node_api.process_transaction_records(records=tx_records)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=20)

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, maker_balance_pre - maker_fee)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, taker_balance_pre - taker_fee)

    assert await nft_wallet_maker.get_nft_count() == 1
    assert await nft_wallet_taker.get_nft_count() == 1
