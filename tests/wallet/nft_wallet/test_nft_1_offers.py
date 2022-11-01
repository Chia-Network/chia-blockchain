from __future__ import annotations

import asyncio
import logging
from secrets import token_bytes
from typing import Any, Callable, Coroutine, Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64, uint128
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import create_asset_id, match_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_memos import compute_memos

# from clvm_tools.binutils import disassemble
from tests.util.wallet_is_synced import wallets_are_synced

logging.getLogger("aiosqlite").setLevel(logging.INFO)  # Too much logging on debug level


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32) -> bool:
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


def mempool_not_empty(fnapi: FullNodeSimulator) -> bool:
    return len(fnapi.full_node.mempool_manager.mempool.spends) > 0


async def farm_blocks_until(
    predicate_f: Callable[[], Coroutine[Any, Any, bool]], fnapi: FullNodeSimulator, ph: bytes32
) -> None:
    for i in range(50):
        await fnapi.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        if await predicate_f():
            return None
        await asyncio.sleep(0.3)
    raise TimeoutError()


async def get_nft_count(wallet: NFTWallet) -> int:
    return len(await wallet.get_current_nfts())


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_nft_offer_sell_nft(two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, funds)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(
        metadata,
        target_puzhash,
        royalty_puzhash,
        royalty_basis_pts,
        did_id,
    )
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, get_nft_count, 1, nft_wallet_maker)

    # TAKER SETUP -  NO DID
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 0

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    xch_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch = {nft_to_offer_asset_id: -1, wallet_maker.id(): xch_requested}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_did_nft_for_xch, {}, fee=maker_fee
    )

    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1
    assert not mempool_not_empty(full_node_api)
    peer = wallet_node_taker.get_full_node_peer()
    assert peer is not None

    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=uint64(taker_fee)
    )

    await time_out_assert(20, mempool_not_empty, True, full_node_api)

    assert error is None
    assert success is True
    assert trade_take is not None

    async def maker_0_taker_1() -> bool:
        return (
            len(await nft_wallet_maker.get_current_nfts()) == 0 and len(await nft_wallet_taker.get_current_nfts()) == 1
        )

    await farm_blocks_until(maker_0_taker_1, full_node_api, ph_token)
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, get_nft_count, 0, nft_wallet_maker)
    await time_out_assert(20, get_nft_count, 1, nft_wallet_taker)

    # assert payments and royalties
    expected_royalty = uint64(xch_requested * royalty_basis_pts / 10000)
    expected_maker_balance = funds - 2 - maker_fee + xch_requested + expected_royalty
    expected_taker_balance = funds - taker_fee - xch_requested - expected_royalty
    await time_out_assert(20, wallet_maker.get_confirmed_balance, expected_maker_balance)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, expected_taker_balance)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_nft_offer_request_nft(two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, funds)

    did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, uint64(1)
    )
    spend_bundle_list = await wallet_node_taker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_taker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, wallet_taker.get_pending_change_balance, 0)

    hex_did_id = did_wallet_taker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_taker
    royalty_puzhash = ph_taker
    royalty_basis_pts = uint16(200)

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET DID TAKER", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )
    await time_out_assert(20, wallet_taker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, funds - 1)

    sb = await nft_wallet_taker.generate_new_nft(
        metadata,
        target_puzhash,
        royalty_puzhash,
        royalty_basis_pts,
        did_id,
    )
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, get_nft_count, 1, nft_wallet_taker)

    # MAKER SETUP -  NO DID
    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET MAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 0
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1

    nft_to_request = coins_taker[0]
    nft_to_request_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_request.full_puzzle))

    assert isinstance(nft_to_request_info, PuzzleInfo)
    nft_to_request_asset_id = create_asset_id(nft_to_request_info)
    xch_offered = 1000
    maker_fee = 10
    driver_dict = {nft_to_request_asset_id: nft_to_request_info}

    offer_dict = {nft_to_request_asset_id: 1, wallet_maker.id(): -xch_offered}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(offer_dict, driver_dict, fee=maker_fee)

    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = wallet_node_taker.get_full_node_peer()
    assert peer is not None
    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=uint64(taker_fee)
    )
    await time_out_assert(20, mempool_not_empty, True, full_node_api)
    assert error is None
    assert success is True
    assert trade_take is not None

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    async def maker_1_taker_0() -> bool:
        return (
            len(await nft_wallet_maker.get_current_nfts()) == 1 and len(await nft_wallet_taker.get_current_nfts()) == 0
        )

    await farm_blocks_until(maker_1_taker_0, full_node_api, ph_token)

    # assert payments and royalties
    expected_royalty = uint64(xch_offered * royalty_basis_pts / 10000)
    expected_maker_balance = funds - maker_fee - xch_offered - expected_royalty
    expected_taker_balance = funds - 2 - taker_fee + xch_offered + expected_royalty
    await time_out_assert(20, wallet_maker.get_confirmed_balance, expected_maker_balance)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, expected_taker_balance)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_nft_offer_sell_did_to_did(two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, funds)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, wallet_maker.get_pending_change_balance, 0)

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds - 1)

    sb = await nft_wallet_maker.generate_new_nft(
        metadata,
        target_puzhash,
        royalty_puzhash,
        royalty_basis_pts,
        did_id,
    )
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, get_nft_count, 1, nft_wallet_maker)

    # TAKER SETUP -  WITH DID
    did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, uint64(1)
    )
    spend_bundle_list_taker = await wallet_node_taker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_taker.id()
    )

    spend_bundle_taker = spend_bundle_list_taker[0].spend_bundle
    await time_out_assert_not_none(
        5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle_taker.name()
    )

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, wallet_taker.get_pending_change_balance, 0)

    hex_did_id_taker = did_wallet_taker.get_my_DID()
    did_id_taker = bytes32.fromhex(hex_did_id_taker)

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER", did_id=did_id_taker
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 0

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    xch_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch = {nft_to_offer_asset_id: -1, wallet_maker.id(): xch_requested}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_did_nft_for_xch, {}, fee=maker_fee
    )

    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = wallet_node_taker.get_full_node_peer()
    assert peer is not None
    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=uint64(taker_fee)
    )
    await time_out_assert(20, mempool_not_empty, True, full_node_api)
    assert error is None
    assert success is True
    assert trade_take is not None

    async def maker_0_taker_1() -> bool:
        return (
            len(await nft_wallet_maker.get_current_nfts()) == 0
            and len(wallet_taker.wallet_state_manager.wallets) == 4
            and len(await wallet_taker.wallet_state_manager.wallets[4].get_current_nfts()) == 1
        )

    await farm_blocks_until(maker_0_taker_1, full_node_api, ph_token)

    await time_out_assert(20, get_nft_count, 0, nft_wallet_maker)
    # assert nnew nft wallet is created for taker
    await time_out_assert(20, len, 4, wallet_taker.wallet_state_manager.wallets)
    await time_out_assert(20, get_nft_count, 1, wallet_taker.wallet_state_manager.wallets[4])
    assert (await wallet_taker.wallet_state_manager.wallets[4].get_current_nfts())[0].nft_id == nft_to_offer_asset_id
    # assert payments and royalties
    expected_royalty = uint64(xch_requested * royalty_basis_pts / 10000)
    expected_maker_balance = funds - 2 - maker_fee + xch_requested + expected_royalty
    expected_taker_balance = funds - 1 - taker_fee - xch_requested - expected_royalty
    await time_out_assert(20, wallet_maker.get_confirmed_balance, expected_maker_balance)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, expected_taker_balance)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_nft_offer_sell_nft_for_cat(two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, funds)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(
        metadata,
        target_puzhash,
        royalty_puzhash,
        royalty_basis_pts,
        did_id,
    )
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, get_nft_count, 1, nft_wallet_maker)

    # TAKER SETUP -  NO DID
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 0

    # Create new CAT and wallets for maker and taker
    # Trade them between maker and taker to ensure multiple coins for each cat
    cats_to_mint = 100000
    cats_to_trade = uint64(10000)
    async with wallet_node_maker.wallet_state_manager.lock:
        full_node_api.full_node.log.warning(
            f"Mempool size: {len(full_node_api.full_node.mempool_manager.mempool.spends)}"
        )
        cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(cats_to_mint)
        )
        await time_out_assert(20, mempool_not_empty, True, full_node_api)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, cat_wallet_maker.get_confirmed_balance, cats_to_mint)
    await time_out_assert(20, cat_wallet_maker.get_unconfirmed_balance, cats_to_mint)

    cat_wallet_taker: CATWallet = await CATWallet.create_wallet_for_cat(
        wallet_node_taker.wallet_state_manager, wallet_taker, cat_wallet_maker.get_asset_id()
    )

    ph_taker_cat_1 = await wallet_taker.get_new_puzzlehash()
    ph_taker_cat_2 = await wallet_taker.get_new_puzzlehash()
    cat_tx_records = await cat_wallet_maker.generate_signed_transaction(
        [cats_to_trade, cats_to_trade], [ph_taker_cat_1, ph_taker_cat_2], memos=[[ph_taker_cat_1], [ph_taker_cat_2]]
    )
    for tx_record in cat_tx_records:
        await wallet_maker.wallet_state_manager.add_pending_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()  # type: ignore
        )
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)
    maker_cat_balance = cats_to_mint - (2 * cats_to_trade)
    taker_cat_balance = 2 * cats_to_trade
    await time_out_assert(20, cat_wallet_maker.get_confirmed_balance, maker_cat_balance)
    await time_out_assert(20, cat_wallet_taker.get_confirmed_balance, taker_cat_balance)
    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    cats_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch = {nft_to_offer_asset_id: -1, cat_wallet_maker.id(): cats_requested}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_did_nft_for_xch, {}, fee=maker_fee
    )

    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = wallet_node_taker.get_full_node_peer()
    assert peer is not None
    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=uint64(taker_fee)
    )
    await time_out_assert(20, mempool_not_empty, True, full_node_api)
    assert error is None
    assert success is True
    assert trade_take is not None

    async def maker_0_taker_1() -> bool:
        return (
            len(await nft_wallet_maker.get_current_nfts()) == 0 and len(await nft_wallet_taker.get_current_nfts()) == 1
        )

    await farm_blocks_until(maker_0_taker_1, full_node_api, ph_token)

    # assert payments and royalties
    expected_royalty = uint64(cats_requested * royalty_basis_pts / 10000)
    expected_maker_balance = funds - 2 - cats_to_mint - maker_fee
    expected_taker_balance = funds - taker_fee
    expected_maker_cat_balance = maker_cat_balance + cats_requested + expected_royalty
    expected_taker_cat_balance = taker_cat_balance - cats_requested - expected_royalty
    await time_out_assert(20, wallet_maker.get_confirmed_balance, expected_maker_balance)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, expected_taker_balance)
    await time_out_assert(20, cat_wallet_maker.get_confirmed_balance, expected_maker_cat_balance)
    await time_out_assert(20, cat_wallet_taker.get_confirmed_balance, expected_taker_cat_balance)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.parametrize("test_change", [True, False])
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_nft_offer_request_nft_for_cat(two_wallet_nodes: Any, trusted: bool, test_change: bool) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, funds)

    did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, uint64(1)
    )
    spend_bundle_list = await wallet_node_taker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_taker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, wallet_taker.get_pending_change_balance, 0)
    await time_out_assert(20, wallet_taker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_taker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_taker
    royalty_puzhash = ph_taker
    royalty_basis_pts = uint16(5000)  # 50%

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET DID TAKER", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_taker.generate_new_nft(
        metadata,
        target_puzhash,
        royalty_puzhash,
        royalty_basis_pts,
        did_id,
    )
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, get_nft_count, 1, nft_wallet_taker)

    # MAKER SETUP -  NO DID
    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET MAKER"
    )

    # maker create offer: NFT for CAT
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 0
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1

    # Create new CAT and wallets for maker and taker
    # Trade them between maker and taker to ensure multiple coins for each cat
    cats_to_mint = 100000
    cats_to_trade = uint64(20000)
    async with wallet_node_maker.wallet_state_manager.lock:
        cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(cats_to_mint)
        )
        await time_out_assert(20, mempool_not_empty, True, full_node_api)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, cat_wallet_maker.get_confirmed_balance, cats_to_mint)
    await time_out_assert(20, cat_wallet_maker.get_unconfirmed_balance, cats_to_mint)

    cat_wallet_taker: CATWallet = await CATWallet.create_wallet_for_cat(
        wallet_node_taker.wallet_state_manager, wallet_taker, cat_wallet_maker.get_asset_id()
    )
    if test_change:
        cat_1 = await wallet_maker.get_new_puzzlehash()
        cat_2 = await wallet_maker.get_new_puzzlehash()
    else:
        cat_1 = await wallet_taker.get_new_puzzlehash()
        cat_2 = await wallet_taker.get_new_puzzlehash()
    puzzle_hashes = [cat_1, cat_2]
    amounts = [cats_to_trade, cats_to_trade]
    if test_change:
        ph_taker_cat_1 = await wallet_taker.get_new_puzzlehash()
        extra_change = cats_to_mint - (2 * cats_to_trade)
        amounts.append(uint64(extra_change))
        puzzle_hashes.append(ph_taker_cat_1)
    cat_tx_records = await cat_wallet_maker.generate_signed_transaction(amounts, puzzle_hashes)
    for tx_record in cat_tx_records:
        await wallet_maker.wallet_state_manager.add_pending_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()  # type: ignore
        )
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)
    if test_change:
        taker_cat_balance = cats_to_mint - (2 * cats_to_trade)
        maker_cat_balance = 2 * cats_to_trade
    else:
        maker_cat_balance = cats_to_mint - (2 * cats_to_trade)
        taker_cat_balance = 2 * cats_to_trade
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, maker_cat_balance)
    await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, taker_cat_balance)

    nft_to_request = coins_taker[0]
    nft_to_request_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_request.full_puzzle))
    nft_to_request_asset_id: bytes32 = create_asset_id(nft_to_request_info)  # type: ignore
    cats_requested = 10000
    maker_fee = uint64(433)
    driver_dict = {nft_to_request_asset_id: nft_to_request_info}

    offer_dict = {nft_to_request_asset_id: 1, cat_wallet_maker.id(): -cats_requested}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(offer_dict, driver_dict, fee=maker_fee)

    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = wallet_node_taker.get_full_node_peer()
    assert peer is not None
    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer), peer, fee=uint64(taker_fee)
    )
    await time_out_assert(20, mempool_not_empty, True, full_node_api)
    assert error is None
    assert success is True
    assert trade_take is not None

    async def maker_1_taker_0() -> bool:
        return (
            len(await nft_wallet_maker.get_current_nfts()) == 1 and len(await nft_wallet_taker.get_current_nfts()) == 0
        )

    await farm_blocks_until(maker_1_taker_0, full_node_api, ph_token)

    # assert payments and royalties
    expected_royalty = uint64(cats_requested * royalty_basis_pts / 10000)
    expected_maker_balance = funds - cats_to_mint - maker_fee
    expected_taker_balance = funds - 2 - taker_fee
    expected_maker_cat_balance = maker_cat_balance - cats_requested - expected_royalty
    expected_taker_cat_balance = taker_cat_balance + cats_requested + expected_royalty
    await time_out_assert(20, wallet_maker.get_confirmed_balance, expected_maker_balance)
    await time_out_assert(20, wallet_taker.get_confirmed_balance, expected_taker_balance)
    await time_out_assert(20, cat_wallet_maker.get_confirmed_balance, expected_maker_cat_balance)
    await time_out_assert(20, cat_wallet_taker.get_confirmed_balance, expected_taker_cat_balance)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_nft_offer_sell_cancel(two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for _ in range(2):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker], full_node_api)

    funds = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 3)])

    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker], full_node_api)

    await time_out_assert(20, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(20, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(20, wallet_maker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(
        metadata,
        target_puzhash,
        royalty_puzhash,
        royalty_basis_pts,
        did_id,
    )
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker], full_node_api)

    await time_out_assert(20, get_nft_count, 1, nft_wallet_maker)

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    xch_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch = {nft_to_offer_asset_id: -1, wallet_maker.id(): xch_requested}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_did_nft_for_xch, {}, fee=maker_fee
    )

    FEE = uint64(2000000000000)
    txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=FEE)

    async def get_trade_and_status(trade_manager: Any, trade: Any) -> TradeStatus:
        trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
        return TradeStatus(trade_rec.status)

    await time_out_assert(20, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    for tx in txs:
        if tx.spend_bundle is not None:
            await time_out_assert(20, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx.spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker], full_node_api)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)


@pytest.mark.parametrize(
    "trusted",
    [True],
)
@pytest.mark.asyncio
async def test_nft_offer_sell_cancel_in_batch(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )

    await time_out_assert(10, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, funds)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(15, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(10, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(10, wallet_maker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_maker.generate_new_nft(
        metadata,
        target_puzhash,
        royalty_puzhash,
        royalty_basis_pts,
        did_id,
    )
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(10, get_nft_count, 1, nft_wallet_maker)

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    xch_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch = {nft_to_offer_asset_id: -1, wallet_maker.id(): xch_requested}

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        offer_did_nft_for_xch, {}, fee=maker_fee
    )

    FEE = uint64(2000000000000)
    txs = await trade_manager_maker.cancel_pending_offers([trade_make], fee=FEE, secure=True)

    async def get_trade_and_status(trade_manager: Any, trade: Any) -> TradeStatus:
        trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
        return TradeStatus(trade_rec.status)

    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    for tx in txs:
        if tx.spend_bundle is not None:
            await time_out_assert(15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx.spend_bundle.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_complex_nft_offer(two_wallet_nodes: Any, trusted: Any) -> None:
    """
    This test is going to create an offer where the maker offers 1 NFT and 1 CAT for 2 NFTs, an XCH and a CAT
    """
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wsm_maker = wallet_node_maker.wallet_state_manager
    wsm_taker = wallet_node_taker.wallet_state_manager
    wallet_maker = wsm_maker.main_wallet
    wallet_taker = wsm_taker.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}
    wallet_node_maker.config["automatically_add_unknown_cats"] = True
    wallet_node_taker.config["automatically_add_unknown_cats"] = True

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    # Need money for fees and offering
    for i in range(0, 2):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(30, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    funds_maker = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 3)])
    funds_taker = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 4)])

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds_maker)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds_maker)
    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds_taker)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds_taker)

    CAT_AMOUNT = uint64(100000000)
    async with wsm_maker.lock:
        cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
            wsm_maker, wallet_maker, {"identifier": "genesis_by_id"}, CAT_AMOUNT
        )
    async with wsm_maker.lock:
        cat_wallet_taker: CATWallet = await CATWallet.create_new_cat_wallet(
            wsm_taker, wallet_taker, {"identifier": "genesis_by_id"}, CAT_AMOUNT
        )
    cat_spend_bundle_maker = (
        await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_maker.id())
    )[0].spend_bundle
    cat_spend_bundle_taker = (
        await wallet_node_taker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_taker.id())
    )[0].spend_bundle
    await time_out_assert_not_none(
        5, full_node_api.full_node.mempool_manager.get_spendbundle, cat_spend_bundle_maker.name()
    )
    await time_out_assert_not_none(
        5, full_node_api.full_node.mempool_manager.get_spendbundle, cat_spend_bundle_taker.name()
    )

    # We'll need these later
    basic_nft_wallet_maker = await NFTWallet.create_new_nft_wallet(wsm_maker, wallet_maker, name="NFT WALLET MAKER")
    basic_nft_wallet_taker = await NFTWallet.create_new_nft_wallet(wsm_taker, wallet_taker, name="NFT WALLET TAKER")

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(wsm_maker, wallet_maker, uint64(1))
    did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(wsm_taker, wallet_taker, uint64(1))
    did_spend_bundle_maker = (
        await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet_maker.id())
    )[0].spend_bundle
    did_spend_bundle_taker = (
        await wallet_node_taker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet_taker.id())
    )[0].spend_bundle

    await time_out_assert_not_none(
        5, full_node_api.full_node.mempool_manager.get_spendbundle, did_spend_bundle_maker.name()
    )
    await time_out_assert_not_none(
        5, full_node_api.full_node.mempool_manager.get_spendbundle, did_spend_bundle_taker.name()
    )

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds_maker = funds_maker - 1 - CAT_AMOUNT
    funds_taker = funds_taker - 1 - CAT_AMOUNT

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds_maker)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds_maker)
    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds_taker)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds_taker)
    await time_out_assert(30, cat_wallet_maker.get_confirmed_balance, CAT_AMOUNT)
    await time_out_assert(30, cat_wallet_maker.get_unconfirmed_balance, CAT_AMOUNT)
    await time_out_assert(30, cat_wallet_taker.get_confirmed_balance, CAT_AMOUNT)
    await time_out_assert(30, cat_wallet_taker.get_unconfirmed_balance, CAT_AMOUNT)

    did_id_maker = bytes32.fromhex(did_wallet_maker.get_my_DID())
    did_id_taker = bytes32.fromhex(did_wallet_taker.get_my_DID())
    target_puzhash_maker = ph_maker
    target_puzhash_taker = ph_taker
    royalty_puzhash_maker = ph_maker
    royalty_puzhash_taker = ph_taker
    royalty_basis_pts_maker = uint16(200)
    royalty_basis_pts_taker_1 = uint16(500)
    royalty_basis_pts_taker_2 = uint16(100)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id_maker
    )
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET DID 1", did_id=did_id_taker
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb_maker = await nft_wallet_maker.generate_new_nft(
        metadata,
        target_puzhash_maker,
        royalty_puzhash_maker,
        royalty_basis_pts_maker,
        did_id_maker,
    )
    sb_taker_1 = await nft_wallet_taker.generate_new_nft(
        metadata,
        target_puzhash_taker,
        royalty_puzhash_taker,
        royalty_basis_pts_taker_1,
        did_id_taker,
    )
    assert sb_maker is not None
    assert sb_taker_1 is not None
    await time_out_assert_not_none(10, full_node_api.full_node.mempool_manager.get_spendbundle, sb_maker.name())
    await time_out_assert_not_none(10, full_node_api.full_node.mempool_manager.get_spendbundle, sb_taker_1.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds_maker -= 1
    funds_taker -= 1

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds_maker)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds_maker)
    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds_taker)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds_taker)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_maker)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_taker)

    # MAke one more NFT for the taker
    sb_taker_2 = await nft_wallet_taker.generate_new_nft(
        metadata,
        target_puzhash_taker,
        royalty_puzhash_taker,
        royalty_basis_pts_taker_2,
        did_id_taker,
    )
    assert sb_taker_2 is not None
    await time_out_assert_not_none(10, full_node_api.full_node.mempool_manager.get_spendbundle, sb_taker_2.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds_taker -= 1

    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds_taker)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds_taker)
    await time_out_assert(30, get_nft_count, 2, nft_wallet_taker)

    trade_manager_maker = wsm_maker.trade_manager
    trade_manager_taker = wsm_taker.trade_manager
    maker_nfts = await nft_wallet_maker.get_current_nfts()
    taker_nfts = await nft_wallet_taker.get_current_nfts()
    nft_to_offer_asset_id_maker: bytes32 = maker_nfts[0].nft_id
    nft_to_offer_asset_id_taker_1: bytes32 = taker_nfts[0].nft_id
    nft_to_offer_asset_id_taker_2: bytes32 = taker_nfts[1].nft_id
    XCH_REQUESTED = 2000000000000
    CAT_REQUESTED = 100000
    FEE = uint64(2000000000000)

    complex_nft_offer = {
        nft_to_offer_asset_id_maker: -1,
        cat_wallet_maker.id(): CAT_REQUESTED * -1,
        1: XCH_REQUESTED,
        nft_to_offer_asset_id_taker_1: 1,
        nft_to_offer_asset_id_taker_2: 1,
        bytes32.from_hexstr(cat_wallet_taker.get_asset_id()): CAT_REQUESTED,
    }

    driver_dict = {
        nft_to_offer_asset_id_taker_1: match_puzzle(uncurry_puzzle(taker_nfts[0].full_puzzle)),
        nft_to_offer_asset_id_taker_2: match_puzzle(uncurry_puzzle(taker_nfts[1].full_puzzle)),
        bytes32.from_hexstr(cat_wallet_taker.get_asset_id()): PuzzleInfo(
            {
                "type": "CAT",
                "tail": "0x" + cat_wallet_taker.get_asset_id(),
            }
        ),
    }

    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        complex_nft_offer, driver_dict=driver_dict, fee=FEE
    )
    assert error is None
    assert success
    assert trade_make is not None

    success, trade_take, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        wallet_node_taker.get_full_node_peer(),
        fee=FEE,
    )
    assert error is None
    assert success
    assert trade_take is not None
    await time_out_assert(20, mempool_not_empty, True, full_node_api)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    # Now let's make sure the final wallet state is correct
    maker_royalty_summary = NFTWallet.royalty_calculation(
        {
            nft_to_offer_asset_id_maker: (royalty_puzhash_maker, royalty_basis_pts_maker),
        },
        {
            None: uint64(XCH_REQUESTED),
            bytes32.from_hexstr(cat_wallet_taker.get_asset_id()): uint64(CAT_REQUESTED),
        },
    )
    taker_royalty_summary = NFTWallet.royalty_calculation(
        {
            nft_to_offer_asset_id_taker_1: (royalty_puzhash_taker, royalty_basis_pts_taker_1),
            nft_to_offer_asset_id_taker_2: (royalty_puzhash_taker, royalty_basis_pts_taker_2),
        },
        {
            bytes32.from_hexstr(cat_wallet_maker.get_asset_id()): uint64(CAT_REQUESTED),
        },
    )
    maker_xch_royalties_expected = maker_royalty_summary[nft_to_offer_asset_id_maker][0]["amount"]
    maker_cat_royalties_expected = maker_royalty_summary[nft_to_offer_asset_id_maker][1]["amount"]
    taker_cat_royalties_expected = (
        taker_royalty_summary[nft_to_offer_asset_id_taker_1][0]["amount"]
        + taker_royalty_summary[nft_to_offer_asset_id_taker_2][0]["amount"]
    )
    funds_maker = int(funds_maker - FEE + XCH_REQUESTED + maker_xch_royalties_expected)
    funds_taker = int(funds_taker - FEE - XCH_REQUESTED - maker_xch_royalties_expected)

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds_maker)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds_maker)
    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds_taker)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds_taker)

    async def get_cat_wallet_and_check_balance(asset_id: str, wsm: Any) -> uint128:
        cat_wallet = await wsm.get_wallet_for_asset_id(asset_id)
        if cat_wallet is None:
            return uint128(0)
        else:
            return uint128(await cat_wallet.get_confirmed_balance())

    await time_out_assert(
        30,
        get_cat_wallet_and_check_balance,
        CAT_REQUESTED + maker_cat_royalties_expected,
        cat_wallet_taker.get_asset_id(),
        wsm_maker,
    )
    await time_out_assert(
        30,
        get_cat_wallet_and_check_balance,
        CAT_REQUESTED + taker_cat_royalties_expected,
        cat_wallet_maker.get_asset_id(),
        wsm_taker,
    )
    maker_nfts = await basic_nft_wallet_maker.get_current_nfts()
    taker_nfts = await basic_nft_wallet_taker.get_current_nfts()
    await time_out_assert(30, len, 2, maker_nfts)
    await time_out_assert(30, len, 1, taker_nfts)

    assert nft_to_offer_asset_id_maker == taker_nfts[0].nft_id
    assert nft_to_offer_asset_id_taker_1 in [nft.nft_id for nft in maker_nfts]
    assert nft_to_offer_asset_id_taker_2 in [nft.nft_id for nft in maker_nfts]
