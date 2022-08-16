import asyncio
import logging
from secrets import token_bytes
from typing import Any, Callable, Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import create_asset_id, match_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
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


async def farm_blocks_until(predicate_f: Callable[[], bool], fnapi: FullNodeSimulator, ph: bytes32) -> None:
    for i in range(50):
        await fnapi.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        if predicate_f():
            return None
        await asyncio.sleep(0.3)
    raise TimeoutError()


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

    await time_out_assert(20, len, 1, nft_wallet_maker.my_nft_coins)

    # TAKER SETUP -  NO DID
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = nft_wallet_maker.my_nft_coins
    assert len(coins_maker) == 1
    coins_taker = nft_wallet_taker.my_nft_coins
    assert len(coins_taker) == 0

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
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

    def maker_0_taker_1() -> bool:
        return len(nft_wallet_maker.my_nft_coins) == 0 and len(nft_wallet_taker.my_nft_coins) == 1

    await farm_blocks_until(maker_0_taker_1, full_node_api, ph_token)
    await time_out_assert(20, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node_api)

    await time_out_assert(20, len, 0, nft_wallet_maker.my_nft_coins)
    await time_out_assert(20, len, 1, nft_wallet_taker.my_nft_coins)

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

    await time_out_assert(20, len, 1, nft_wallet_taker.my_nft_coins)

    # MAKER SETUP -  NO DID
    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET MAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = nft_wallet_maker.my_nft_coins
    assert len(coins_maker) == 0
    coins_taker = nft_wallet_taker.my_nft_coins
    assert len(coins_taker) == 1

    nft_to_request = coins_taker[0]
    nft_to_request_info: Optional[PuzzleInfo] = match_puzzle(nft_to_request.full_puzzle)

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

    def maker_1_taker_0() -> bool:
        return len(nft_wallet_maker.my_nft_coins) == 1 and len(nft_wallet_taker.my_nft_coins) == 0

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

    await time_out_assert(20, len, 1, nft_wallet_maker.my_nft_coins)

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

    coins_maker = nft_wallet_maker.my_nft_coins
    assert len(coins_maker) == 1
    coins_taker = nft_wallet_taker.my_nft_coins
    assert len(coins_taker) == 0

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
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

    def maker_0_taker_1() -> bool:
        return (
            len(nft_wallet_maker.my_nft_coins) == 0
            and len(wallet_taker.wallet_state_manager.wallets) == 4
            and len(wallet_taker.wallet_state_manager.wallets[4].my_nft_coins) == 1
        )

    await farm_blocks_until(maker_0_taker_1, full_node_api, ph_token)

    await time_out_assert(20, len, 0, nft_wallet_maker.my_nft_coins)
    # assert nnew nft wallet is created for taker
    await time_out_assert(20, len, 4, wallet_taker.wallet_state_manager.wallets)
    await time_out_assert(20, len, 1, wallet_taker.wallet_state_manager.wallets[4].my_nft_coins)
    assert wallet_taker.wallet_state_manager.wallets[4].my_nft_coins[0].nft_id == nft_to_offer_asset_id
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

    await time_out_assert(20, len, 1, nft_wallet_maker.my_nft_coins)

    # TAKER SETUP -  NO DID
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = nft_wallet_maker.my_nft_coins
    assert len(coins_maker) == 1
    coins_taker = nft_wallet_taker.my_nft_coins
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
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
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

    def maker_0_taker_1() -> bool:
        return len(nft_wallet_maker.my_nft_coins) == 0 and len(nft_wallet_taker.my_nft_coins) == 1

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

    await time_out_assert(20, len, 1, nft_wallet_taker.my_nft_coins)

    # MAKER SETUP -  NO DID
    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, name="NFT WALLET MAKER"
    )

    # maker create offer: NFT for CAT
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = nft_wallet_maker.my_nft_coins
    assert len(coins_maker) == 0
    coins_taker = nft_wallet_taker.my_nft_coins
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
    nft_to_request_info: Optional[PuzzleInfo] = match_puzzle(nft_to_request.full_puzzle)
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

    def maker_1_taker_0() -> bool:
        return len(nft_wallet_maker.my_nft_coins) == 1 and len(nft_wallet_taker.my_nft_coins) == 0

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

    await time_out_assert(20, len, 1, nft_wallet_maker.my_nft_coins)

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager

    coins_maker = nft_wallet_maker.my_nft_coins
    assert len(coins_maker) == 1

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
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

    await time_out_assert(10, len, 1, nft_wallet_maker.my_nft_coins)

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager

    coins_maker = nft_wallet_maker.my_nft_coins
    assert len(coins_maker) == 1

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(nft_to_offer.full_puzzle)
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
