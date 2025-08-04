from __future__ import annotations

import logging
from typing import Any, Optional

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import Program
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import create_asset_id, match_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer, OfferSummary
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.uncurried_puzzle import uncurry_puzzle

logging.getLogger("aiosqlite").setLevel(logging.INFO)  # Too much logging on debug level


async def get_nft_count(wallet: NFTWallet) -> int:
    return await wallet.get_nft_count()


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("zero_royalties", [True, False])
@pytest.mark.anyio
async def test_nft_offer_sell_nft(wallet_environments: WalletTestFramework, zero_royalties: bool) -> None:
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wallet_maker = env_maker.xch_wallet
    wallet_taker = env_taker.xch_wallet

    env_maker.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_maker = await action_scope.get_puzzle_hash(wallet_maker.wallet_state_manager)

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_maker.wallet_state_manager, wallet_maker, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(0 if zero_royalties else 200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_maker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash,
            royalty_puzhash,
            royalty_basis_pts,
            did_id,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    # TAKER SETUP -  NO DID
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    assert await nft_wallet_taker.get_nft_count() == 0

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    xch_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch: OfferSummary = {nft_to_offer_asset_id: -1, wallet_maker.id(): xch_requested}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_did_nft_for_xch, action_scope, {}, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1
    peer = env_taker.node.get_full_node_peer()

    [_maker_offer], signing_response = await env_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=uint64(taker_fee)
        )

    assert trade_take is not None

    expected_royalty = uint64(xch_requested * royalty_basis_pts / 10000)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": maker_fee,
                        "<=#max_send_amount": maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {},
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": (xch_requested + expected_royalty) - maker_fee,
                        "unconfirmed_wallet_balance": (xch_requested + expected_royalty) - maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "unspent_coin_count": 2 if expected_royalty > 0 else 1,
                        "pending_coin_removal_count": -1,
                    },
                    "did": {},
                    "nft": {
                        "unspent_coin_count": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(taker_fee + xch_requested + expected_royalty),
                        "<=#spendable_balance": -(taker_fee + xch_requested + expected_royalty),
                        "<=#max_send_amount": -(taker_fee + xch_requested + expected_royalty),
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "init": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(taker_fee + xch_requested + expected_royalty),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )

    await time_out_assert(20, get_nft_count, 0, nft_wallet_maker)
    await time_out_assert(20, get_nft_count, 1, nft_wallet_taker)


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("zero_royalties", [True, False])
@pytest.mark.anyio
async def test_nft_offer_request_nft(wallet_environments: WalletTestFramework, zero_royalties: bool) -> None:
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wallet_maker = env_maker.xch_wallet
    wallet_taker = env_taker.xch_wallet

    env_maker.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }

    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_taker = await action_scope.get_puzzle_hash(wallet_taker.wallet_state_manager)

    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_taker.wallet_state_manager, wallet_taker, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    hex_did_id = did_wallet_taker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_taker
    royalty_puzhash = ph_taker
    royalty_basis_pts = uint16(0 if zero_royalties else 200)

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_taker.wallet_state_manager, wallet_taker, name="NFT WALLET DID TAKER", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    async with nft_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_taker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash,
            royalty_puzhash,
            royalty_basis_pts,
            did_id,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    await time_out_assert(20, get_nft_count, 1, nft_wallet_taker)

    # MAKER SETUP -  NO DID
    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_maker.wallet_state_manager, wallet_maker, name="NFT WALLET MAKER"
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager

    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1

    assert await nft_wallet_maker.get_nft_count() == 0
    nft_to_request = coins_taker[0]
    nft_to_request_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_request.full_puzzle))

    assert isinstance(nft_to_request_info, PuzzleInfo)
    nft_to_request_asset_id = create_asset_id(nft_to_request_info)
    assert nft_to_request_asset_id is not None
    xch_offered = 1000
    maker_fee = uint64(10)
    driver_dict = {nft_to_request_asset_id: nft_to_request_info}

    offer_dict: OfferSummary = {nft_to_request_asset_id: 1, wallet_maker.id(): -xch_offered}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_dict, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = env_taker.node.get_full_node_peer()
    [_maker_offer], signing_response = await env_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=uint64(taker_fee)
        )
    assert trade_take is not None

    expected_royalty = uint64(xch_offered * royalty_basis_pts / 10000)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -(maker_fee + xch_offered + expected_royalty),
                        "<=#max_send_amount": -(maker_fee + xch_offered + expected_royalty),
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "init": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(maker_fee + xch_offered + expected_royalty),
                        "unconfirmed_wallet_balance": -(maker_fee + xch_offered + expected_royalty),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        # royalty information doesn't show up in unconfirmed balance
                        "unconfirmed_wallet_balance": xch_offered - taker_fee,
                        "<=#spendable_balance": -taker_fee,
                        "<=#max_send_amount": -taker_fee,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {},
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": xch_offered + expected_royalty - taker_fee,
                        "unconfirmed_wallet_balance": expected_royalty,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "unspent_coin_count": 2 if expected_royalty > 0 else 1,
                        "pending_coin_removal_count": -1,
                    },
                    "did": {},
                    "nft": {
                        "unspent_coin_count": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("zero_royalties", [True, False])
@pytest.mark.anyio
async def test_nft_offer_sell_did_to_did(wallet_environments: WalletTestFramework, zero_royalties: bool) -> None:
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wallet_maker = env_maker.xch_wallet
    wallet_taker = env_taker.xch_wallet

    env_maker.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft1": 3,
        "nft0": 4,
    }

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_maker = await action_scope.get_puzzle_hash(wallet_maker.wallet_state_manager)

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_maker.wallet_state_manager, wallet_maker, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(0 if zero_royalties else 200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_maker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash,
            royalty_puzhash,
            royalty_basis_pts,
            did_id,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    # TAKER SETUP -  WITH DID
    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_taker.wallet_state_manager, wallet_taker, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    hex_did_id_taker = did_wallet_taker.get_my_DID()
    did_id_taker = bytes32.fromhex(hex_did_id_taker)

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER", did_id=did_id_taker
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    assert await nft_wallet_taker.get_nft_count() == 0
    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    xch_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch: OfferSummary = {nft_to_offer_asset_id: -1, wallet_maker.id(): xch_requested}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_did_nft_for_xch, action_scope, {}, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = env_taker.node.get_full_node_peer()
    [_maker_offer], signing_response = await env_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=uint64(taker_fee)
        )
    assert trade_take is not None

    expected_royalty = uint64(xch_requested * royalty_basis_pts / 10000)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": maker_fee,
                        "<=#max_send_amount": maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {},
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": (xch_requested + expected_royalty) - maker_fee,
                        "unconfirmed_wallet_balance": (xch_requested + expected_royalty) - maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "unspent_coin_count": 2 if expected_royalty > 0 else 1,
                        "pending_coin_removal_count": -1,
                    },
                    "did": {},
                    "nft": {
                        "unspent_coin_count": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(taker_fee + xch_requested + expected_royalty),
                        "<=#spendable_balance": -(taker_fee + xch_requested + expected_royalty),
                        "<=#max_send_amount": -(taker_fee + xch_requested + expected_royalty),
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(taker_fee + xch_requested + expected_royalty),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "nft0": {
                        "init": True,
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )

    nft_0_wallet_taker = env_taker.wallet_state_manager.wallets[uint32(4)]
    assert isinstance(nft_0_wallet_taker, NFTWallet)
    await time_out_assert(20, get_nft_count, 0, nft_wallet_maker)
    await time_out_assert(20, get_nft_count, 1, nft_0_wallet_taker)
    assert await nft_0_wallet_taker.nft_store.get_nft_by_id(nft_to_offer_asset_id) is not None


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("zero_royalties", [True, False])
@pytest.mark.anyio
async def test_nft_offer_sell_nft_for_cat(wallet_environments: WalletTestFramework, zero_royalties: bool) -> None:
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wallet_maker = env_maker.xch_wallet
    wallet_taker = env_taker.xch_wallet

    env_maker.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
        "cat": 4,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "nft": 2,
        "cat": 3,
    }

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_maker = await action_scope.get_puzzle_hash(wallet_maker.wallet_state_manager)

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_maker.wallet_state_manager, wallet_maker, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(0 if zero_royalties else 200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_maker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash,
            royalty_puzhash,
            royalty_basis_pts,
            did_id,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    # TAKER SETUP -  NO DID
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_taker.wallet_state_manager, wallet_taker, name="NFT WALLET TAKER"
    )

    await env_taker.change_balances({"nft": {"init": True}})

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
    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            env_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            uint64(cats_to_mint),
            action_scope,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    cat_wallet_taker: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
        env_taker.wallet_state_manager, wallet_taker, cat_wallet_maker.get_asset_id()
    )

    await env_taker.change_balances({"cat": {"init": True}})

    with wallet_environments.new_puzzle_hashes_allowed():
        async with wallet_taker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            ph_taker_cat_1 = await action_scope.get_puzzle_hash(wallet_taker.wallet_state_manager)
            ph_taker_cat_2 = await action_scope.get_puzzle_hash(
                wallet_taker.wallet_state_manager, override_reuse_puzhash_with=False
            )
    async with cat_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await cat_wallet_maker.generate_signed_transaction(
            [cats_to_trade, cats_to_trade],
            [ph_taker_cat_1, ph_taker_cat_2],
            action_scope,
            memos=[[ph_taker_cat_1], [ph_taker_cat_2]],
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "cat": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    maker_cat_balance = cats_to_mint - (2 * cats_to_trade)
    taker_cat_balance = 2 * cats_to_trade
    await time_out_assert(20, cat_wallet_maker.get_confirmed_balance, maker_cat_balance)
    await time_out_assert(20, cat_wallet_taker.get_confirmed_balance, taker_cat_balance)
    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    nft_to_offer_asset_id: bytes32 = create_asset_id(nft_to_offer_info)  # type: ignore
    cats_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch: OfferSummary = {nft_to_offer_asset_id: -1, cat_wallet_maker.id(): cats_requested}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_did_nft_for_xch, action_scope, {}, fee=maker_fee
        )

    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = env_taker.node.get_full_node_peer()
    [_maker_offer], signing_response = await env_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=uint64(taker_fee)
        )
    assert trade_take is not None

    # assert payments and royalties
    expected_royalty = uint64(cats_requested * royalty_basis_pts / 10000)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {},
                    "did": {},
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -maker_fee,
                        "unconfirmed_wallet_balance": -maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": cats_requested + expected_royalty,
                        "confirmed_wallet_balance": cats_requested + expected_royalty,
                        "spendable_balance": cats_requested + expected_royalty,
                        "max_send_amount": cats_requested + expected_royalty,
                        "unspent_coin_count": 2 if expected_royalty > 0 else 1,
                    },
                    "did": {},
                    "nft": {
                        "unspent_coin_count": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -taker_fee,
                        "<=#spendable_balance": -taker_fee,
                        "<=#max_send_amount": -taker_fee,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": -(cats_requested + expected_royalty),
                        "<=#spendable_balance": -(cats_requested + expected_royalty),
                        "<=#max_send_amount": -(cats_requested + expected_royalty),
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "init": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -taker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": -(cats_requested + expected_royalty),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("test_change", [True, False])
@pytest.mark.anyio
async def test_nft_offer_request_nft_for_cat(wallet_environments: WalletTestFramework, test_change: bool) -> None:
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wallet_maker = env_maker.xch_wallet
    wallet_taker = env_taker.xch_wallet

    env_maker.wallet_aliases = {
        "xch": 1,
        "nft": 2,
        "cat": 3,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
        "cat": 4,
    }

    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_taker = await action_scope.get_puzzle_hash(wallet_taker.wallet_state_manager)

    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_taker.wallet_state_manager, wallet_taker, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    hex_did_id = did_wallet_taker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_taker
    royalty_puzhash = ph_taker
    royalty_basis_pts = uint16(5000)  # 50%

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_taker.wallet_state_manager, wallet_taker, name="NFT WALLET DID TAKER", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    async with nft_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_taker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash,
            royalty_puzhash,
            royalty_basis_pts,
            did_id,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    await time_out_assert(20, get_nft_count, 1, nft_wallet_taker)

    # MAKER SETUP -  NO DID
    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_maker.wallet_state_manager, wallet_maker, name="NFT WALLET MAKER"
    )

    await env_maker.change_balances({"nft": {"init": True}})

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
    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            env_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            uint64(cats_to_mint),
            action_scope,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await CATWallet.get_or_create_wallet_for_cat(
        env_taker.wallet_state_manager, wallet_taker, cat_wallet_maker.get_asset_id()
    )

    await env_taker.change_balances({"cat": {"init": True}})

    with wallet_environments.new_puzzle_hashes_allowed():
        if test_change:
            async with wallet_maker.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=True
            ) as action_scope:
                cat_1 = await action_scope.get_puzzle_hash(wallet_maker.wallet_state_manager)
                cat_2 = await action_scope.get_puzzle_hash(
                    wallet_maker.wallet_state_manager, override_reuse_puzhash_with=False
                )
        else:
            async with wallet_taker.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=True
            ) as action_scope:
                cat_1 = await action_scope.get_puzzle_hash(wallet_taker.wallet_state_manager)
                cat_2 = await action_scope.get_puzzle_hash(
                    wallet_taker.wallet_state_manager, override_reuse_puzhash_with=False
                )
    puzzle_hashes = [cat_1, cat_2]
    amounts = [cats_to_trade, cats_to_trade]
    if test_change:
        async with wallet_taker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            ph_taker_cat_1 = await action_scope.get_puzzle_hash(wallet_taker.wallet_state_manager)
        extra_change = cats_to_mint - (2 * cats_to_trade)
        amounts.append(uint64(extra_change))
        puzzle_hashes.append(ph_taker_cat_1)
    else:
        extra_change = 0  # for mypy sake, not useful

    async with cat_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await cat_wallet_maker.generate_signed_transaction(amounts, puzzle_hashes, action_scope)

    taker_diff = extra_change if test_change else 2 * cats_to_trade
    maker_diff = -taker_diff
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": maker_diff,
                        "<=#spendable_balance": maker_diff,
                        "<=#max_send_amount": maker_diff,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": maker_diff,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 1,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1 if test_change else 0,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": taker_diff,
                        "unconfirmed_wallet_balance": taker_diff,
                        "spendable_balance": taker_diff,
                        "max_send_amount": taker_diff,
                        "unspent_coin_count": 1 if test_change else 2,
                    },
                },
            ),
        ]
    )

    nft_to_request = coins_taker[0]
    nft_to_request_info = match_puzzle(uncurry_puzzle(nft_to_request.full_puzzle))
    assert nft_to_request_info is not None
    nft_to_request_asset_id = create_asset_id(nft_to_request_info)
    assert nft_to_request_asset_id is not None
    cats_requested = 10000
    maker_fee = uint64(433)
    driver_dict = {nft_to_request_asset_id: nft_to_request_info}

    offer_dict: OfferSummary = {nft_to_request_asset_id: 1, cat_wallet_maker.id(): -cats_requested}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_dict, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = 1

    peer = env_taker.node.get_full_node_peer()
    [_maker_offer], signing_response = await env_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=uint64(taker_fee)
        )
    assert trade_take is not None

    expected_royalty = uint64(cats_requested * royalty_basis_pts / 10000)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {
                        "<=#spendable_balance": -(cats_requested + expected_royalty),
                        "<=#max_send_amount": -(cats_requested + expected_royalty),
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "init": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -maker_fee,
                        "unconfirmed_wallet_balance": -maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": -(cats_requested + expected_royalty),
                        "unconfirmed_wallet_balance": -(cats_requested + expected_royalty),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -taker_fee,
                        "<=#spendable_balance": -taker_fee,
                        "<=#max_send_amount": -taker_fee,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {
                        # Normally taker is not royalty holder so this is an edge case
                        "unconfirmed_wallet_balance": cats_requested  # + expected_royalty,
                    },
                    "did": {},
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -taker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": cats_requested + expected_royalty,
                        "unconfirmed_wallet_balance": expected_royalty,  # only find out after sync
                        "spendable_balance": cats_requested + expected_royalty,
                        "max_send_amount": cats_requested + expected_royalty,
                        "unspent_coin_count": 2,
                    },
                    "did": {},
                    "nft": {
                        "unspent_coin_count": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    assert len(await nft_wallet_maker.get_current_nfts()) == 1
    assert len(await nft_wallet_taker.get_current_nfts()) == 0


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [2]}], indirect=True)
@pytest.mark.anyio
async def test_nft_offer_sell_cancel(wallet_environments: WalletTestFramework) -> None:
    env_maker = wallet_environments.environments[0]
    wallet_maker = env_maker.xch_wallet

    env_maker.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_maker = await action_scope.get_puzzle_hash(wallet_maker.wallet_state_manager)

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_maker.wallet_state_manager, wallet_maker, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            )
        ]
    )

    hex_did_id = did_wallet_maker.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)
    target_puzhash = ph_maker
    royalty_puzhash = ph_maker
    royalty_basis_pts = uint16(200)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_maker.wallet_state_manager, wallet_maker, name="NFT WALLET DID 1", did_id=did_id
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    await env_maker.change_balances({"nft": {"init": True}})

    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_maker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash,
            royalty_puzhash,
            royalty_basis_pts,
            did_id,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft": {
                        "set_remainder": True,
                    },
                },
            )
        ]
    )

    await time_out_assert(20, get_nft_count, 1, nft_wallet_maker)

    # maker create offer: NFT for xch
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager

    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1

    nft_to_offer = coins_maker[0]
    nft_to_offer_info = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    assert nft_to_offer_info is not None
    nft_to_offer_asset_id = create_asset_id(nft_to_offer_info)
    assert nft_to_offer_asset_id is not None
    xch_requested = 1000
    maker_fee = uint64(433)

    offer_did_nft_for_xch: OfferSummary = {nft_to_offer_asset_id: -1, wallet_maker.id(): xch_requested}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        _success, trade_make, _error = await trade_manager_maker.create_offer_for_ids(
            offer_did_nft_for_xch, action_scope, {}, fee=maker_fee
        )
    assert trade_make is not None

    FEE = uint64(2000000000000)
    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], action_scope, fee=FEE, secure=True)

    async def get_trade_and_status(trade_manager: Any, trade: Any) -> TradeStatus:
        trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
        return TradeStatus(trade_rec.status)

    await time_out_assert(20, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -FEE,
                        "<=#spendable_balance": -FEE,
                        "<=#max_send_amount": -FEE,
                        "pending_coin_removal_count": 3,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -FEE,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "unspent_coin_count": -2,
                        "pending_coin_removal_count": -3,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize(
    "royalty_pts",
    [
        (200, 500, 500),
        (200, 500, 500),
        (0, 0, 0),  # test that we can have 0 royalty
        (10000, 10001, 10005),  # tests 100% royalty is not allowed
        (100000, 10001, 10005),  # 1000% shouldn't work
    ],
)
@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [3, 3], "config_overrides": {"automatically_add_unknown_cats": True}}],
    indirect=True,
)
@pytest.mark.anyio
async def test_complex_nft_offer(wallet_environments: WalletTestFramework, royalty_pts: tuple[int, int, int]) -> None:
    """
    This test is going to create an offer where the maker offers 1 NFT and 1 CAT for 2 NFTs, an XCH and a CAT
    """
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wsm_maker = env_maker.wallet_state_manager
    wsm_taker = env_taker.wallet_state_manager
    wallet_maker = wsm_maker.main_wallet
    wallet_taker = wsm_taker.main_wallet

    env_maker.wallet_aliases = {
        "xch": 1,
        "cat_maker": 2,
        "nft0": 3,
        "did": 4,
        "nft1": 5,
        "cat_taker": 6,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "cat_taker": 2,
        "nft0": 3,
        "did": 4,
        "nft1": 5,
        "cat_maker": 6,
    }

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_maker = await action_scope.get_puzzle_hash(wallet_maker.wallet_state_manager)
    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        ph_taker = await action_scope.get_puzzle_hash(wallet_taker.wallet_state_manager)

    CAT_AMOUNT = uint64(100000000)
    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            wsm_maker, wallet_maker, {"identifier": "genesis_by_id"}, CAT_AMOUNT, action_scope
        )
    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_taker = await CATWallet.create_new_cat_wallet(
            wsm_taker, wallet_taker, {"identifier": "genesis_by_id"}, CAT_AMOUNT, action_scope
        )
    await env_maker.change_balances({"cat_maker": {"init": True}})
    await env_taker.change_balances({"cat_taker": {"init": True}})

    # We'll need these later
    basic_nft_wallet_maker = await NFTWallet.create_new_nft_wallet(wsm_maker, wallet_maker, name="NFT WALLET MAKER")
    basic_nft_wallet_taker = await NFTWallet.create_new_nft_wallet(wsm_taker, wallet_taker, name="NFT WALLET TAKER")
    await env_maker.change_balances({"nft0": {"init": True}})
    await env_taker.change_balances({"nft0": {"init": True}})

    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
            wsm_maker, wallet_maker, uint64(1), action_scope
        )
    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
            wsm_taker, wallet_taker, uint64(1), action_scope
        )
    await env_maker.change_balances({"did": {"init": True}})
    await env_taker.change_balances({"did": {"init": True}})

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat_maker": {
                        "set_remainder": True,
                    },
                    "nft0": {},
                    "did": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat_maker": {
                        "set_remainder": True,
                    },
                    "nft0": {},
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat_taker": {
                        "set_remainder": True,
                    },
                    "nft0": {},
                    "did": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "cat_taker": {
                        "set_remainder": True,
                    },
                    "nft0": {},
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    did_id_maker = bytes32.fromhex(did_wallet_maker.get_my_DID())
    did_id_taker = bytes32.fromhex(did_wallet_taker.get_my_DID())
    target_puzhash_maker = ph_maker
    target_puzhash_taker = ph_taker
    royalty_puzhash_maker = ph_maker
    royalty_puzhash_taker = ph_taker
    royalty_basis_pts_maker, royalty_basis_pts_taker_1, royalty_basis_pts_taker_2 = (
        royalty_pts[0],
        uint16(royalty_pts[1]),
        uint16(royalty_pts[2]),
    )

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wsm_maker, wallet_maker, name="NFT WALLET DID 1", did_id=did_id_maker
    )
    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wsm_taker, wallet_taker, name="NFT WALLET DID 1", did_id=did_id_taker
    )
    await env_maker.change_balances({"nft1": {"init": True}})
    await env_taker.change_balances({"nft1": {"init": True}})

    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )
    if royalty_basis_pts_maker > 65535:
        with pytest.raises(ValueError):
            async with nft_wallet_maker.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=False
            ) as action_scope:
                await nft_wallet_maker.generate_new_nft(
                    metadata,
                    action_scope,
                    target_puzhash_maker,
                    royalty_puzhash_maker,
                    royalty_basis_pts_maker,  # type: ignore
                    did_id_maker,
                )
        return
    else:
        async with nft_wallet_maker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            await nft_wallet_maker.generate_new_nft(
                metadata,
                action_scope,
                target_puzhash_maker,
                royalty_puzhash_maker,
                uint16(royalty_basis_pts_maker),
                did_id_maker,
            )

    async with nft_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_taker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash_taker,
            royalty_puzhash_taker,
            royalty_basis_pts_taker_1,
            did_id_taker,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    await time_out_assert(30, get_nft_count, 1, nft_wallet_maker)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_taker)

    # MAke one more NFT for the taker
    async with nft_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_taker.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash_taker,
            royalty_puzhash_taker,
            royalty_basis_pts_taker_2,
            did_id_taker,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "nft1": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    await time_out_assert(30, get_nft_count, 2, nft_wallet_taker)

    trade_manager_maker = wsm_maker.trade_manager
    trade_manager_taker = wsm_taker.trade_manager
    maker_nfts = await nft_wallet_maker.get_current_nfts()
    taker_nfts = await nft_wallet_taker.get_current_nfts()
    nft_to_offer_asset_id_maker: bytes32 = maker_nfts[0].nft_id
    nft_to_offer_asset_id_taker_1: bytes32 = taker_nfts[0].nft_id
    nft_to_offer_asset_id_taker_2: bytes32 = taker_nfts[1].nft_id
    if royalty_basis_pts_maker > 60000:
        XCH_REQUESTED = 20000
        CAT_REQUESTED = 1000
        FEE = uint64(20000)
    else:
        XCH_REQUESTED = 2000000000000
        CAT_REQUESTED = 100000
        FEE = uint64(2000000000000)

    complex_nft_offer: OfferSummary = {
        nft_to_offer_asset_id_maker: -1,
        cat_wallet_maker.id(): CAT_REQUESTED * -1,
        1: XCH_REQUESTED,
        nft_to_offer_asset_id_taker_1: 1,
        nft_to_offer_asset_id_taker_2: 1,
        bytes32.from_hexstr(cat_wallet_taker.get_asset_id()): CAT_REQUESTED,
    }

    nft_taker_1_info = match_puzzle(uncurry_puzzle(taker_nfts[0].full_puzzle))
    nft_taker_2_info = match_puzzle(uncurry_puzzle(taker_nfts[1].full_puzzle))
    assert nft_taker_1_info is not None
    assert nft_taker_2_info is not None
    driver_dict = {
        nft_to_offer_asset_id_taker_1: nft_taker_1_info,
        nft_to_offer_asset_id_taker_2: nft_taker_2_info,
        bytes32.from_hexstr(cat_wallet_taker.get_asset_id()): PuzzleInfo(
            {
                "type": "CAT",
                "tail": "0x" + cat_wallet_taker.get_asset_id(),
            }
        ),
    }

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            complex_nft_offer, action_scope, driver_dict=driver_dict, fee=FEE
        )
    assert error is None
    assert success
    assert trade_make is not None

    [maker_offer], signing_response = await wsm_maker.sign_offers([Offer.from_bytes(trade_make.offer)])
    if royalty_basis_pts_maker == 10000:
        with pytest.raises(ValueError):
            async with trade_manager_taker.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
            ) as action_scope:
                trade_take = await trade_manager_taker.respond_to_offer(
                    Offer.from_bytes(trade_make.offer),
                    env_taker.node.get_full_node_peer(),
                    action_scope,
                    fee=FEE,
                )
        # all done for this test
        return
    else:
        async with trade_manager_taker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
        ) as action_scope:
            trade_take = await trade_manager_taker.respond_to_offer(
                maker_offer,
                env_taker.node.get_full_node_peer(),
                action_scope,
                fee=FEE,
            )
    assert trade_take is not None

    maker_royalty_summary = NFTWallet.royalty_calculation(
        {
            nft_to_offer_asset_id_maker: (royalty_puzhash_maker, uint16(royalty_basis_pts_maker)),
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

    xch_coins = int(XCH_REQUESTED / 1_750_000_000_000) + 2
    fee_coins = int(FEE / 1_750_000_000_000) + 1 if FEE > 1_750_000_000_000 else 1
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -FEE,
                        "<=#max_send_amount": -FEE,
                        "pending_coin_removal_count": fee_coins,
                    },
                    "cat_maker": {
                        "<=#spendable_balance": -CAT_REQUESTED - taker_cat_royalties_expected,
                        "<=#max_send_amount": -CAT_REQUESTED - taker_cat_royalties_expected,
                        "pending_coin_removal_count": 1,
                    },
                    "nft1": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": XCH_REQUESTED + maker_xch_royalties_expected - FEE,
                        "confirmed_wallet_balance": XCH_REQUESTED + maker_xch_royalties_expected - FEE,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -fee_coins,
                        # Parametrizations make unspent_coin_count too complicated
                        "set_remainder": True,
                    },
                    "cat_maker": {
                        "unconfirmed_wallet_balance": -CAT_REQUESTED - taker_cat_royalties_expected,
                        "confirmed_wallet_balance": -CAT_REQUESTED - taker_cat_royalties_expected,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "cat_taker": {
                        "init": True,
                        "unconfirmed_wallet_balance": CAT_REQUESTED + maker_cat_royalties_expected,
                        "confirmed_wallet_balance": CAT_REQUESTED + maker_cat_royalties_expected,
                        "spendable_balance": CAT_REQUESTED + maker_cat_royalties_expected,
                        "max_send_amount": CAT_REQUESTED + maker_cat_royalties_expected,
                        # Parametrizations make unspent_coin_count too complicated
                        "set_remainder": True,
                    },
                    "nft1": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                    "nft0": {
                        "unspent_coin_count": 2,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -XCH_REQUESTED - maker_xch_royalties_expected - FEE,
                        "<=#spendable_balance": -XCH_REQUESTED - maker_xch_royalties_expected - FEE,
                        "<=#max_send_amount": -XCH_REQUESTED - maker_xch_royalties_expected - FEE,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": xch_coins + fee_coins,
                    },
                    "cat_taker": {
                        "unconfirmed_wallet_balance": -CAT_REQUESTED - maker_cat_royalties_expected,
                        "<=#spendable_balance": -CAT_REQUESTED - maker_cat_royalties_expected,
                        "<=#max_send_amount": -CAT_REQUESTED - maker_cat_royalties_expected,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    # Royalties don't factor into unconfirmed balance calculations
                    "cat_maker": {
                        "init": True,
                        "unconfirmed_wallet_balance": CAT_REQUESTED,
                    },
                    "nft1": {
                        "pending_coin_removal_count": 2,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -XCH_REQUESTED - maker_xch_royalties_expected - FEE,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -fee_coins - xch_coins,
                        # Parametrizations make unspent_coin_count too complicated
                        "set_remainder": True,
                    },
                    "cat_taker": {
                        "confirmed_wallet_balance": -CAT_REQUESTED - maker_cat_royalties_expected,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "cat_maker": {
                        "confirmed_wallet_balance": CAT_REQUESTED + taker_cat_royalties_expected,
                        "unconfirmed_wallet_balance": taker_cat_royalties_expected,
                        "spendable_balance": CAT_REQUESTED + taker_cat_royalties_expected,
                        "max_send_amount": CAT_REQUESTED + taker_cat_royalties_expected,
                        # Parametrizations make unspent_coin_count too complicated
                        "set_remainder": True,
                    },
                    "nft1": {
                        "unspent_coin_count": -2,
                        "pending_coin_removal_count": -2,
                    },
                    "nft0": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )

    maker_nfts = await basic_nft_wallet_maker.get_current_nfts()
    taker_nfts = await basic_nft_wallet_taker.get_current_nfts()
    assert len(maker_nfts) == 2
    assert len(taker_nfts) == 1

    assert nft_to_offer_asset_id_maker == taker_nfts[0].nft_id
    assert nft_to_offer_asset_id_taker_1 in [nft.nft_id for nft in maker_nfts]
    assert nft_to_offer_asset_id_taker_2 in [nft.nft_id for nft in maker_nfts]

    # Try another permutation
    HALF_XCH_REQUESTED = int(XCH_REQUESTED / 2)
    complex_nft_offer = {
        cat_wallet_maker.id(): CAT_REQUESTED * -1,
        1: HALF_XCH_REQUESTED,
        bytes32.from_hexstr(cat_wallet_taker.get_asset_id()): CAT_REQUESTED,
        nft_to_offer_asset_id_maker: 1,
    }

    maker_nft_info = match_puzzle(uncurry_puzzle(taker_nfts[0].full_puzzle))
    assert maker_nft_info is not None
    driver_dict = {
        nft_to_offer_asset_id_maker: maker_nft_info,
        bytes32.from_hexstr(cat_wallet_taker.get_asset_id()): PuzzleInfo(
            {
                "type": "CAT",
                "tail": "0x" + cat_wallet_taker.get_asset_id(),
            }
        ),
    }

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            complex_nft_offer, action_scope, driver_dict=driver_dict, fee=uint64(0)
        )
    assert error is None
    assert success
    assert trade_make is not None

    [maker_offer], signing_response = await wsm_maker.sign_offers([Offer.from_bytes(trade_make.offer)])
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            env_taker.node.get_full_node_peer(),
            action_scope,
            fee=uint64(0),
        )
    assert trade_take is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "cat_maker": {
                        "<=#spendable_balance": -CAT_REQUESTED,
                        "<=#max_send_amount": -CAT_REQUESTED,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": HALF_XCH_REQUESTED,
                        "unconfirmed_wallet_balance": HALF_XCH_REQUESTED,
                        "spendable_balance": HALF_XCH_REQUESTED,
                        "max_send_amount": HALF_XCH_REQUESTED,
                        # parametrization makes unspent_coin_count difficult
                        "set_remainder": True,
                    },
                    "cat_maker": {
                        "confirmed_wallet_balance": -CAT_REQUESTED,
                        "unconfirmed_wallet_balance": -CAT_REQUESTED,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                        # parametrization makes unspent_coin_count difficult
                        "set_remainder": True,
                    },
                    "cat_taker": {
                        "confirmed_wallet_balance": CAT_REQUESTED,
                        "unconfirmed_wallet_balance": CAT_REQUESTED,
                        "spendable_balance": CAT_REQUESTED,
                        "max_send_amount": CAT_REQUESTED,
                        # parametrization makes unspent_coin_count difficult
                        "set_remainder": True,
                    },
                    "nft0": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -HALF_XCH_REQUESTED,
                        "<=#spendable_balance": -HALF_XCH_REQUESTED,
                        "<=#max_send_amount": -HALF_XCH_REQUESTED,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "cat_maker": {
                        "unconfirmed_wallet_balance": CAT_REQUESTED,
                    },
                    "cat_taker": {
                        "unconfirmed_wallet_balance": -CAT_REQUESTED,
                        "<=#spendable_balance": -CAT_REQUESTED,
                        "<=#max_send_amount": -CAT_REQUESTED,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft0": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -HALF_XCH_REQUESTED,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "cat_maker": {
                        "confirmed_wallet_balance": CAT_REQUESTED,
                        "spendable_balance": CAT_REQUESTED,
                        "max_send_amount": CAT_REQUESTED,
                        # parametrization makes unspent_coin_count difficult
                        "set_remainder": True,
                    },
                    "cat_taker": {
                        "confirmed_wallet_balance": -CAT_REQUESTED,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "nft0": {
                        "unspent_coin_count": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    # Now let's make sure the final wallet state is correct
    await time_out_assert(20, get_nft_count, 3, basic_nft_wallet_maker)
    await time_out_assert(20, get_nft_count, 0, basic_nft_wallet_taker)
    assert await basic_nft_wallet_maker.nft_store.get_nft_by_id(nft_to_offer_asset_id_maker) is not None
