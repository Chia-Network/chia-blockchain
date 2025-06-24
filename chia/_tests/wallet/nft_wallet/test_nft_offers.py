from __future__ import annotations

from typing import Optional, Union

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import Program
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import create_asset_id, match_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.debug_spend_bundle import disassemble


async def get_trade_and_status(trade_manager, trade) -> TradeStatus:  # type: ignore
    trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
    return TradeStatus(trade_rec.status)


@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_offer_with_fee(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_maker = env_0.xch_wallet
    wallet_taker = env_1.xch_wallet
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager
    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
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
        await nft_wallet_maker.generate_new_nft(metadata, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(pre_block_balance_updates={"nft": {"init": True}}),
        ]
    )
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1

    assert await nft_wallet_taker.get_nft_count() == 0
    # MAKE FIRST TRADE: 1 NFT for 100 xch

    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    assert nft_info is not None
    nft_asset_id = create_asset_id(nft_info)
    assert nft_asset_id is not None
    driver_dict: dict[bytes32, PuzzleInfo] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch: dict[Union[int, bytes32], int] = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_nft_for_xch, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    [_maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    peer = env_1.node.get_full_node_peer()
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            peer,
            action_scope,
            fee=taker_fee,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -maker_fee + xch_request,
                        "confirmed_wallet_balance": -maker_fee + xch_request,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(xch_request + taker_fee),
                        "<=#spendable_balance": -taker_fee,
                        "<=#max_send_amount": -taker_fee,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(xch_request + taker_fee),
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

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1
    assert await nft_wallet_maker.get_nft_count() == 0
    # MAKE SECOND TRADE: 100 xch for 1 NFT

    nft_to_buy = coins_taker[0]
    nft_to_buy_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_buy.full_puzzle))
    assert nft_to_buy_info is not None
    nft_to_buy_asset_id = create_asset_id(nft_to_buy_info)
    assert nft_to_buy_asset_id is not None
    driver_dict_to_buy: dict[bytes32, PuzzleInfo] = {nft_to_buy_asset_id: nft_to_buy_info}

    xch_offered = 1000
    maker_fee = uint64(10)
    offer_xch_for_nft: dict[Union[int, bytes32], int] = {wallet_maker.id(): -xch_offered, nft_to_buy_asset_id: 1}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_xch_for_nft, action_scope, driver_dict_to_buy, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    [_maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=taker_fee
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -(xch_offered + maker_fee),
                        "<=#max_send_amount": -(xch_offered + maker_fee),
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(xch_offered + maker_fee),
                        "confirmed_wallet_balance": -(xch_offered + maker_fee),
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
                        "unconfirmed_wallet_balance": -taker_fee + xch_offered,
                        "<=#spendable_balance": -(xch_offered + maker_fee),
                        "<=#max_send_amount": -(xch_offered + maker_fee),
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -taker_fee + xch_offered,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
        ]
    )

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    assert await nft_wallet_maker.get_nft_count() == 1
    assert await nft_wallet_taker.get_nft_count() == 0


@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_offer_cancellations(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    wallet_maker = env_0.xch_wallet
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
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
        await nft_wallet_maker.generate_new_nft(metadata, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(pre_block_balance_updates={"nft": {"init": True}}),
        ]
    )
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1

    # maker creates offer and cancels
    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    assert nft_info is not None
    nft_asset_id = create_asset_id(nft_info)
    assert nft_asset_id is not None
    driver_dict: dict[bytes32, PuzzleInfo] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch: dict[Union[bytes32, int], int] = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_nft_for_xch, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    await env_0.change_balances(
        {
            "xch": {
                "<=#spendable_balance": -maker_fee,
                "<=#max_send_amount": -maker_fee,
                "pending_coin_removal_count": 1,
            }
        }
    )

    cancel_fee = uint64(10)

    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await trade_manager_maker.cancel_pending_offers(
            [trade_make.trade_id], action_scope, fee=cancel_fee, secure=True
        )

    await time_out_assert(20, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -cancel_fee,
                        "<=#spendable_balance": -cancel_fee,
                        "<=#max_send_amount": -cancel_fee,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -cancel_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -2,  # 1 from make, 1 from cancel
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await time_out_assert(20, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)
    assert await nft_wallet_maker.get_nft_count() == 1


@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_offer_with_metadata_update(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_maker = env_0.xch_wallet
    wallet_taker = env_1.xch_wallet
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager
    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    )

    metadata = Program.to(
        [
            ("mu", []),
            ("lu", []),
            ("sn", uint64(1)),
            ("st", uint64(1)),
        ]
    )

    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_maker.generate_new_nft(metadata, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(pre_block_balance_updates={"nft": {"init": True}}),
        ]
    )
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    assert await nft_wallet_taker.get_nft_count() == 0

    # Maker updates metadata:
    nft_to_update = coins_maker[0]
    url_to_add = "https://new_url.com"
    key = "mu"
    fee_for_update = uint64(10)
    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_maker.update_metadata(nft_to_update, key, url_to_add, action_scope, fee=fee_for_update)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee_for_update,
                        "<=#spendable_balance": -fee_for_update,
                        "<=#max_send_amount": -fee_for_update,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee_for_update,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    coins_maker = await nft_wallet_maker.get_current_nfts()
    updated_nft = coins_maker[0]
    updated_nft_info = match_puzzle(uncurry_puzzle(updated_nft.full_puzzle))
    assert updated_nft_info is not None
    state_layer_info = updated_nft_info.also()
    assert state_layer_info is not None
    assert url_to_add in disassemble(state_layer_info.info["metadata"])

    # MAKE FIRST TRADE: 1 NFT for 100 xch
    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    assert nft_info is not None
    nft_asset_id = create_asset_id(nft_info)
    assert nft_asset_id is not None
    driver_dict: dict[bytes32, PuzzleInfo] = {nft_asset_id: nft_info}

    xch_request = 100
    maker_fee = uint64(10)
    offer_nft_for_xch: dict[Union[bytes32, int], int] = {wallet_maker.id(): xch_request, nft_asset_id: -1}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_nft_for_xch, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    [_maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    peer = env_1.node.get_full_node_peer()
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=taker_fee
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -maker_fee + xch_request,
                        "confirmed_wallet_balance": -maker_fee + xch_request,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(xch_request + taker_fee),
                        "<=#spendable_balance": -taker_fee,
                        "<=#max_send_amount": -taker_fee,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(xch_request + taker_fee),
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

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    assert await nft_wallet_maker.get_nft_count() == 0
    assert await nft_wallet_taker.get_nft_count() == 1


@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_offer_nft_for_cat(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_maker = env_0.xch_wallet
    wallet_taker = env_1.xch_wallet
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager
    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
        "maker cat": 3,
        "taker cat": 4,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
        "taker cat": 3,
        "maker cat": 4,
    }

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
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
        await nft_wallet_maker.generate_new_nft(metadata, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(pre_block_balance_updates={"nft": {"init": True}}),
        ]
    )
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    assert await nft_wallet_taker.get_nft_count() == 0

    # Create two new CATs and wallets for maker and taker
    cats_to_mint = 10000
    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            env_0.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            uint64(cats_to_mint),
            action_scope,
        )

    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_taker = await CATWallet.create_new_cat_wallet(
            env_1.wallet_state_manager,
            wallet_taker,
            {"identifier": "genesis_by_id"},
            uint64(cats_to_mint),
            action_scope,
        )

    # mostly set_remainder here as minting CATs is tested elsewhere
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "maker cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "maker cat": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "taker cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "taker cat": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    wallet_maker_for_taker_cat: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
        env_0.wallet_state_manager, wallet_maker, cat_wallet_taker.get_asset_id()
    )

    await CATWallet.get_or_create_wallet_for_cat(
        env_1.wallet_state_manager, wallet_taker, cat_wallet_maker.get_asset_id()
    )

    # MAKE FIRST TRADE: 1 NFT for 10 taker cats
    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    assert nft_info is not None
    nft_asset_id = create_asset_id(nft_info)
    assert nft_asset_id is not None
    driver_dict: dict[bytes32, PuzzleInfo] = {nft_asset_id: nft_info}

    maker_fee = uint64(10)
    taker_cat_offered = 2500
    offer_nft_for_cat: dict[Union[bytes32, int], int] = {
        nft_asset_id: -1,
        wallet_maker_for_taker_cat.id(): taker_cat_offered,
    }

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_nft_for_cat, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    [_maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    peer = env_1.node.get_full_node_peer()
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            peer,
            action_scope,
            fee=taker_fee,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "taker cat": {
                        "init": True,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -maker_fee,
                        "confirmed_wallet_balance": -maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "taker cat": {
                        "init": True,
                        "unconfirmed_wallet_balance": taker_cat_offered,
                        "confirmed_wallet_balance": taker_cat_offered,
                        "spendable_balance": taker_cat_offered,
                        "max_send_amount": taker_cat_offered,
                        "unspent_coin_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
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
                    "maker cat": {
                        "init": True,
                    },
                    "taker cat": {
                        "unconfirmed_wallet_balance": -taker_cat_offered,
                        "<=#spendable_balance": -taker_cat_offered,
                        "<=#max_send_amount": -taker_cat_offered,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -taker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "taker cat": {
                        "confirmed_wallet_balance": -taker_cat_offered,
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

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1
    assert await nft_wallet_maker.get_nft_count() == 0

    # Make an offer for taker NFT for multiple cats
    maker_cat_amount = 400
    taker_cat_amount = 500

    nft_to_buy = coins_taker[0]
    nft_to_buy_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_buy.full_puzzle))
    assert nft_to_buy_info is not None
    nft_to_buy_asset_id = create_asset_id(nft_to_buy_info)
    assert nft_to_buy_asset_id is not None
    driver_dict_to_buy: dict[bytes32, PuzzleInfo] = {
        nft_to_buy_asset_id: nft_to_buy_info,
    }

    maker_fee = uint64(10)
    offer_multi_cats_for_nft: dict[Union[bytes32, int], int] = {
        nft_to_buy_asset_id: 1,
        wallet_maker_for_taker_cat.id(): -taker_cat_amount,
        cat_wallet_maker.id(): -maker_cat_amount,
    }

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_multi_cats_for_nft, action_scope, driver_dict_to_buy, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    [_maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=taker_fee
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "taker cat": {
                        "<=#spendable_balance": -taker_cat_amount,
                        "<=#max_send_amount": -taker_cat_amount,
                        "pending_coin_removal_count": 1,
                    },
                    "maker cat": {
                        "<=#spendable_balance": -maker_cat_amount,
                        "<=#max_send_amount": -maker_cat_amount,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -maker_fee,
                        "confirmed_wallet_balance": -maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "taker cat": {
                        "unconfirmed_wallet_balance": -taker_cat_amount,
                        "confirmed_wallet_balance": -taker_cat_amount,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "maker cat": {
                        "unconfirmed_wallet_balance": -maker_cat_amount,
                        "confirmed_wallet_balance": -maker_cat_amount,
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
                    "maker cat": {
                        "unconfirmed_wallet_balance": maker_cat_amount,
                    },
                    "taker cat": {
                        "unconfirmed_wallet_balance": taker_cat_amount,
                    },
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
                    "maker cat": {
                        "confirmed_wallet_balance": maker_cat_amount,
                        "spendable_balance": maker_cat_amount,
                        "max_send_amount": maker_cat_amount,
                        "unspent_coin_count": 1,
                    },
                    "taker cat": {
                        "confirmed_wallet_balance": taker_cat_amount,
                        "spendable_balance": taker_cat_amount,
                        "max_send_amount": taker_cat_amount,
                        "unspent_coin_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
        ]
    )

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    assert await nft_wallet_maker.get_nft_count() == 1
    assert await nft_wallet_taker.get_nft_count() == 0


@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_offer_nft_for_nft(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_maker = env_0.xch_wallet
    wallet_taker = env_1.xch_wallet
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager
    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    )

    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    metadata_2 = Program.to(
        [
            ("u", ["https://www.chia.net/image2.html"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F183"),
        ]
    )

    async with nft_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_maker.generate_new_nft(metadata, action_scope)
    async with nft_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_taker.generate_new_nft(metadata_2, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1

    nft_to_offer = coins_maker[0]
    nft_to_offer_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    assert nft_to_offer_info is not None
    nft_to_offer_asset_id = create_asset_id(nft_to_offer_info)
    assert nft_to_offer_asset_id is not None

    nft_to_take = coins_taker[0]
    nft_to_take_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_take.full_puzzle))
    assert nft_to_take_info is not None
    nft_to_take_asset_id = create_asset_id(nft_to_take_info)
    assert nft_to_take_asset_id is not None

    driver_dict: dict[bytes32, PuzzleInfo] = {
        nft_to_offer_asset_id: nft_to_offer_info,
        nft_to_take_asset_id: nft_to_take_info,
    }

    maker_fee = uint64(10)
    offer_nft_for_nft: dict[Union[bytes32, int], int] = {nft_to_take_asset_id: 1, nft_to_offer_asset_id: -1}

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_nft_for_nft, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    taker_fee = uint64(1)

    [_maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    peer = env_1.node.get_full_node_peer()
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), peer, action_scope, fee=taker_fee
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -maker_fee,
                        "confirmed_wallet_balance": -maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {
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
                    "nft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    assert await nft_wallet_maker.get_nft_count() == 1
    assert await nft_wallet_taker.get_nft_count() == 1


@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_offer_nft0_and_xch_for_cat(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_maker = env_0.xch_wallet
    wallet_taker = env_1.xch_wallet
    trade_manager_maker = wallet_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_taker.wallet_state_manager.trade_manager
    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
        "maker cat": 3,
        "taker cat": 4,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
        "taker cat": 3,
        "maker cat": 4,
    }

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1"
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        env_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
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
        await nft_wallet_maker.generate_new_nft(metadata, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(pre_block_balance_updates={"nft": {"init": True}}),
        ]
    )
    coins_maker = await nft_wallet_maker.get_current_nfts()
    assert len(coins_maker) == 1

    assert await nft_wallet_taker.get_nft_count() == 0
    # Create two new CATs and wallets for maker and taker
    cats_to_mint = 10000
    async with wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            env_0.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            uint64(cats_to_mint),
            action_scope,
        )

    async with wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_wallet_taker = await CATWallet.create_new_cat_wallet(
            env_1.wallet_state_manager,
            wallet_taker,
            {"identifier": "genesis_by_id"},
            uint64(cats_to_mint),
            action_scope,
        )

    wallet_maker_for_taker_cat: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
        env_0.wallet_state_manager, wallet_maker, cat_wallet_taker.get_asset_id()
    )

    await CATWallet.get_or_create_wallet_for_cat(
        env_1.wallet_state_manager, wallet_taker, cat_wallet_maker.get_asset_id()
    )

    # mostly set_remainder here as minting CATs is tested elsewhere
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "maker cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                    "taker cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "maker cat": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "maker cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                    "taker cat": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "taker cat": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    # MAKE FIRST TRADE: 1 NFT for 10 taker cats
    nft_to_offer = coins_maker[0]
    nft_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_offer.full_puzzle))
    assert nft_info is not None
    nft_asset_id = create_asset_id(nft_info)
    assert nft_asset_id is not None
    driver_dict: dict[bytes32, PuzzleInfo] = {nft_asset_id: nft_info}

    maker_fee = uint64(10)
    maker_xch_offered = 1000
    taker_cat_offered = 2500
    wallet_maker_id = wallet_maker.id()
    offer_nft_for_cat: dict[Union[bytes32, int], int] = {
        wallet_maker_id: -maker_xch_offered,
        nft_asset_id: -1,
        wallet_maker_for_taker_cat.id(): taker_cat_offered,
    }

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_nft_for_cat, action_scope, driver_dict, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    [maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers([Offer.from_bytes(trade_make.offer)])

    taker_fee = uint64(1)

    peer = env_1.node.get_full_node_peer()
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            maker_offer,
            peer,
            action_scope,
            fee=taker_fee,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -(maker_fee + maker_xch_offered),
                        "<=#max_send_amount": -(maker_fee + maker_xch_offered),
                        "pending_coin_removal_count": 1,
                    },
                    "taker cat": {},
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(maker_fee + maker_xch_offered),
                        "confirmed_wallet_balance": -(maker_fee + maker_xch_offered),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "taker cat": {
                        "unconfirmed_wallet_balance": taker_cat_offered,
                        "confirmed_wallet_balance": taker_cat_offered,
                        "spendable_balance": taker_cat_offered,
                        "max_send_amount": taker_cat_offered,
                        "unspent_coin_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -taker_fee + maker_xch_offered,
                        "<=#spendable_balance": -taker_fee + maker_xch_offered,
                        "<=#max_send_amount": -taker_fee + maker_xch_offered,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "taker cat": {
                        "unconfirmed_wallet_balance": -taker_cat_offered,
                        "<=#spendable_balance": -taker_cat_offered,
                        "<=#max_send_amount": -taker_cat_offered,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -taker_fee + maker_xch_offered,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                    "taker cat": {
                        "confirmed_wallet_balance": -taker_cat_offered,
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

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    coins_taker = await nft_wallet_taker.get_current_nfts()
    assert len(coins_taker) == 1
    assert await nft_wallet_maker.get_nft_count() == 0

    # Make an offer for taker NFT for multiple cats
    maker_cat_amount = 400
    taker_cat_amount = 500

    nft_to_buy = coins_taker[0]
    nft_to_buy_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_to_buy.full_puzzle))
    assert nft_to_buy_info is not None
    nft_to_buy_asset_id = create_asset_id(nft_to_buy_info)
    assert nft_to_buy_asset_id is not None

    driver_dict_to_buy: dict[bytes32, PuzzleInfo] = {
        nft_to_buy_asset_id: nft_to_buy_info,
    }

    maker_fee = uint64(10)
    offer_multi_cats_for_nft: dict[Union[bytes32, int], int] = {
        nft_to_buy_asset_id: 1,
        wallet_maker_for_taker_cat.id(): -taker_cat_amount,
        cat_wallet_maker.id(): -maker_cat_amount,
    }

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            offer_multi_cats_for_nft, action_scope, driver_dict_to_buy, fee=maker_fee
        )
    assert success is True
    assert error is None
    assert trade_make is not None

    [maker_offer], signing_response = await env_0.wallet_state_manager.sign_offers([Offer.from_bytes(trade_make.offer)])

    taker_fee = uint64(1)

    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(maker_offer, peer, action_scope, fee=taker_fee)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -maker_fee,
                        "<=#max_send_amount": -maker_fee,
                        "pending_coin_removal_count": 1,
                    },
                    "taker cat": {
                        "<=#spendable_balance": -taker_cat_amount,
                        "<=#max_send_amount": -taker_cat_amount,
                        "pending_coin_removal_count": 1,
                    },
                    "maker cat": {
                        "<=#spendable_balance": -maker_cat_amount,
                        "<=#max_send_amount": -maker_cat_amount,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -maker_fee,
                        "confirmed_wallet_balance": -maker_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "taker cat": {
                        "unconfirmed_wallet_balance": -taker_cat_amount,
                        "confirmed_wallet_balance": -taker_cat_amount,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "pending_coin_removal_count": -1,
                    },
                    "maker cat": {
                        "unconfirmed_wallet_balance": -maker_cat_amount,
                        "confirmed_wallet_balance": -maker_cat_amount,
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
                    "taker cat": {
                        "unconfirmed_wallet_balance": taker_cat_amount,
                    },
                    "maker cat": {
                        "unconfirmed_wallet_balance": maker_cat_amount,
                    },
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
                    "taker cat": {
                        "confirmed_wallet_balance": taker_cat_amount,
                        "spendable_balance": taker_cat_amount,
                        "max_send_amount": taker_cat_amount,
                        "unspent_coin_count": 1,
                    },
                    "maker cat": {
                        "confirmed_wallet_balance": maker_cat_amount,
                        "spendable_balance": maker_cat_amount,
                        "max_send_amount": maker_cat_amount,
                        "unspent_coin_count": 1,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
        ]
    )

    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(20, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    assert await nft_wallet_maker.get_nft_count() == 1
    assert await nft_wallet_taker.get_nft_count() == 0
