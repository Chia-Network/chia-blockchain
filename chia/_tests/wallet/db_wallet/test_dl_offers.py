from __future__ import annotations

from typing import Any

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.wallet.puzzle_drivers import Solver
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.util.merkle_utils import build_merkle_tree, simplify_merkle_proof


async def is_singleton_confirmed_and_root(dl_wallet: DataLayerWallet, lid: bytes32, root: bytes32) -> bool:
    rec = await dl_wallet.get_latest_singleton(lid)
    if rec is None:
        return False
    if rec.confirmed is True:
        assert rec.confirmed_at_height > 0
        assert rec.timestamp > 0
    return rec.confirmed and rec.root == root


async def get_trade_and_status(trade_manager: Any, trade: TradeRecord) -> TradeStatus:
    trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
    return TradeStatus(trade_rec.status)


def get_parent_branch(value: bytes32, proof: tuple[int, list[bytes32]]) -> tuple[bytes32, tuple[int, list[bytes32]]]:
    branch: bytes32 = simplify_merkle_proof(value, (proof[0], [proof[1][0]]))
    new_proof: tuple[int, list[bytes32]] = (proof[0] >> 1, proof[1][1:])
    return branch, new_proof


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [2, 2]}], indirect=True)
@pytest.mark.anyio
async def test_dl_offers(wallet_environments: WalletTestFramework) -> None:
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wsm_maker = env_maker.wallet_state_manager
    wsm_taker = env_taker.wallet_state_manager

    env_maker.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }

    dl_wallet_maker = await DataLayerWallet.create_new_dl_wallet(wsm_maker)
    dl_wallet_taker = await DataLayerWallet.create_new_dl_wallet(wsm_taker)

    await env_maker.change_balances({"dl": {"init": True}})
    await env_taker.change_balances({"dl": {"init": True}})

    MAKER_ROWS = [bytes32([i] * 32) for i in range(10)]
    TAKER_ROWS = [bytes32([i] * 32) for i in range(10)]
    maker_root, _ = build_merkle_tree(MAKER_ROWS)
    taker_root, _ = build_merkle_tree(TAKER_ROWS)

    fee = uint64(1_999_999_999_999)

    async with dl_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_maker = await dl_wallet_maker.generate_new_reporter(maker_root, action_scope, fee=fee)
    assert await dl_wallet_maker.get_latest_singleton(launcher_id_maker) is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_maker, maker_root)

    async with dl_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_taker = await dl_wallet_taker.generate_new_reporter(taker_root, action_scope, fee=fee)
    assert await dl_wallet_taker.get_latest_singleton(launcher_id_taker) is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_taker, taker_root)

    peer = env_taker.node.get_full_node_peer()
    await dl_wallet_maker.track_new_launcher_id(launcher_id_taker, peer)
    await dl_wallet_taker.track_new_launcher_id(launcher_id_maker, peer)
    await env_maker.change_balances({"dl": {"unspent_coin_count": 1}})
    await env_taker.change_balances({"dl": {"unspent_coin_count": 1}})
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker, maker_root)

    trade_manager_maker = wsm_maker.trade_manager
    trade_manager_taker = wsm_taker.trade_manager

    maker_addition = bytes32([101] * 32)
    taker_addition = bytes32([101] * 32)
    MAKER_ROWS.append(maker_addition)
    TAKER_ROWS.append(taker_addition)
    maker_root, maker_proofs = build_merkle_tree(MAKER_ROWS)
    taker_root, taker_proofs = build_merkle_tree(TAKER_ROWS)
    maker_branch, maker_branch_proof = get_parent_branch(maker_addition, maker_proofs[maker_addition])
    taker_branch, taker_branch_proof = get_parent_branch(taker_addition, taker_proofs[taker_addition])

    fee = uint64(2_000_000_000_000)

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, offer_maker, error = await trade_manager_maker.create_offer_for_ids(
            {launcher_id_maker: -1, launcher_id_taker: 1},
            action_scope,
            solver=Solver(
                {
                    launcher_id_maker.hex(): {
                        "new_root": "0x" + maker_root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + launcher_id_taker.hex(),
                                "values_to_prove": ["0x" + taker_branch.hex()],
                            },
                        ],
                    }
                }
            ),
            fee=fee,
        )
    assert error is None
    assert success is True
    assert offer_maker is not None

    assert await trade_manager_taker.get_offer_summary(Offer.from_bytes(offer_maker.offer)) == {
        "offered": [
            {
                "launcher_id": launcher_id_maker.hex(),
                "new_root": maker_root.hex(),
                "dependencies": [
                    {
                        "launcher_id": launcher_id_taker.hex(),
                        "values_to_prove": [taker_branch.hex()],
                    }
                ],
            }
        ]
    }

    [_maker_offer], signing_response = await wsm_maker.sign_offers([Offer.from_bytes(offer_maker.offer)])
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        offer_taker = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(offer_maker.offer),
            peer,
            action_scope,
            solver=Solver(
                {
                    launcher_id_taker.hex(): {
                        "new_root": "0x" + taker_root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + launcher_id_maker.hex(),
                                "values_to_prove": ["0x" + maker_branch.hex()],
                            },
                        ],
                    },
                    "proofs_of_inclusion": [
                        [
                            maker_root.hex(),
                            str(maker_branch_proof[0]),
                            ["0x" + sibling.hex() for sibling in maker_branch_proof[1]],
                        ],
                        [
                            taker_root.hex(),
                            str(taker_branch_proof[0]),
                            ["0x" + sibling.hex() for sibling in taker_branch_proof[1]],
                        ],
                    ],
                }
            ),
            fee=fee,
        )
    assert offer_taker is not None

    assert await trade_manager_maker.get_offer_summary(Offer.from_bytes(offer_taker.offer)) == {
        "offered": [
            {
                "launcher_id": launcher_id_maker.hex(),
                "new_root": maker_root.hex(),
                "dependencies": [
                    {
                        "launcher_id": launcher_id_taker.hex(),
                        "values_to_prove": [taker_branch.hex()],
                    }
                ],
            },
            {
                "launcher_id": launcher_id_taker.hex(),
                "new_root": taker_root.hex(),
                "dependencies": [
                    {
                        "launcher_id": launcher_id_maker.hex(),
                        "values_to_prove": [maker_branch.hex()],
                    }
                ],
            },
        ]
    }

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "spendable_balance": -fee,
                        "max_send_amount": -fee,
                        "pending_coin_removal_count": 2,
                    },
                    "dl": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "confirmed_wallet_balance": -fee,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -2,
                    },
                    "dl": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "spendable_balance": -fee,
                        "max_send_amount": -fee,
                        "pending_coin_removal_count": 2,
                    },
                    "dl": {
                        "pending_coin_removal_count": 2,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -2,
                    },
                    "dl": {
                        "pending_coin_removal_count": -2,
                    },
                },
            ),
        ]
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker, maker_root)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, offer_maker)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, offer_taker)

    async def is_singleton_generation(wallet: DataLayerWallet, launcher_id: bytes32, generation: int) -> bool:
        latest = await wallet.get_latest_singleton(launcher_id)
        if latest is not None and latest.generation == generation:
            return True
        return False

    await time_out_assert(15, is_singleton_generation, True, dl_wallet_taker, launcher_id_taker, 2)

    async with dl_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await dl_wallet_taker.create_update_state_spend(launcher_id_taker, bytes32([2] * 32), action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [3]}], indirect=True)
@pytest.mark.anyio
async def test_dl_offer_cancellation(wallet_environments: WalletTestFramework) -> None:
    env_maker = wallet_environments.environments[0]
    env_maker.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }

    dl_wallet = await DataLayerWallet.create_new_dl_wallet(env_maker.wallet_state_manager)
    await env_maker.change_balances({"dl": {"init": True}})

    ROWS = [bytes32([i] * 32) for i in range(10)]
    root, _ = build_merkle_tree(ROWS)

    async with dl_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id = await dl_wallet.generate_new_reporter(root, action_scope)
    assert await dl_wallet.get_latest_singleton(launcher_id) is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, root)
    async with dl_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_2 = await dl_wallet.generate_new_reporter(root, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    trade_manager = env_maker.wallet_state_manager.trade_manager

    addition = bytes32([101] * 32)
    ROWS.append(addition)
    root, _proofs = build_merkle_tree(ROWS)

    FEE = uint64(2_000_000_000_000)

    async with trade_manager.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, offer, error = await trade_manager.create_offer_for_ids(
            {launcher_id: -1, launcher_id_2: 1},
            action_scope,
            solver=Solver(
                {
                    launcher_id.hex(): {
                        "new_root": "0x" + root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + launcher_id_2.hex(),
                                "values_to_prove": ["0x" + addition.hex()],
                            },
                        ],
                    }
                }
            ),
            fee=FEE,
        )
    assert error is None
    assert success is True
    assert offer is not None

    await env_maker.change_balances(
        {
            "xch": {
                "spendable_balance": -FEE,
                "max_send_amount": -FEE,
                "pending_coin_removal_count": 2,
            },
            "dl": {
                "pending_coin_removal_count": 1,
            },
        }
    )
    await env_maker.check_balances()

    async with trade_manager.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await trade_manager.cancel_pending_offers([offer.trade_id], action_scope, fee=FEE, secure=True)

    # One outgoing for cancel, one outgoing for fee, one incoming from cancel
    assert len(action_scope.side_effects.transactions) == 3
    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager, offer)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -FEE,
                        "spendable_balance": -FEE,
                        "max_send_amount": -FEE,
                        "pending_coin_removal_count": 2,
                    },
                    "dl": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -FEE,
                        "spendable_balance": FEE,
                        "max_send_amount": FEE,
                        "pending_coin_removal_count": -4,
                        "unspent_coin_count": -2,
                    },
                    "dl": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager, offer)


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [3, 3]}], indirect=True)
@pytest.mark.anyio
async def test_multiple_dl_offers(wallet_environments: WalletTestFramework) -> None:
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wsm_maker = env_maker.wallet_state_manager
    wsm_taker = env_taker.wallet_state_manager

    env_maker.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }
    env_taker.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }

    dl_wallet_maker = await DataLayerWallet.create_new_dl_wallet(wsm_maker)
    dl_wallet_taker = await DataLayerWallet.create_new_dl_wallet(wsm_taker)
    await env_maker.change_balances({"dl": {"init": True}})
    await env_taker.change_balances({"dl": {"init": True}})

    MAKER_ROWS = [bytes32([i] * 32) for i in range(10)]
    TAKER_ROWS = [bytes32([i] * 32) for i in range(10, 20)]
    maker_root, _ = build_merkle_tree(MAKER_ROWS)
    taker_root, _ = build_merkle_tree(TAKER_ROWS)

    fee = uint64(1_999_999_999_999)

    async with dl_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_maker_1 = await dl_wallet_maker.generate_new_reporter(maker_root, action_scope, fee=fee)
    assert await dl_wallet_maker.get_latest_singleton(launcher_id_maker_1) is not None

    async with dl_wallet_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_maker_2 = await dl_wallet_maker.generate_new_reporter(maker_root, action_scope, fee=fee)
    assert await dl_wallet_maker.get_latest_singleton(launcher_id_maker_2) is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_maker_1, maker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_maker_2, maker_root)

    async with dl_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_taker_1 = await dl_wallet_taker.generate_new_reporter(taker_root, action_scope, fee=fee)
    assert await dl_wallet_taker.get_latest_singleton(launcher_id_taker_1) is not None

    async with dl_wallet_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_taker_2 = await dl_wallet_taker.generate_new_reporter(taker_root, action_scope, fee=fee)
    assert await dl_wallet_taker.get_latest_singleton(launcher_id_taker_2) is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "dl": {
                        "set_remainder": True,
                    },
                },
            ),
        ]
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_taker_1, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_taker_2, taker_root)

    peer = env_taker.node.get_full_node_peer()
    await dl_wallet_maker.track_new_launcher_id(launcher_id_taker_1, peer)
    await dl_wallet_maker.track_new_launcher_id(launcher_id_taker_2, peer)
    await dl_wallet_taker.track_new_launcher_id(launcher_id_maker_1, peer)
    await dl_wallet_taker.track_new_launcher_id(launcher_id_maker_2, peer)
    await env_maker.change_balances({"dl": {"unspent_coin_count": 2}})
    await env_taker.change_balances({"dl": {"unspent_coin_count": 2}})
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker_1, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker_2, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker_1, maker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker_2, maker_root)

    trade_manager_maker = wsm_maker.trade_manager
    trade_manager_taker = wsm_taker.trade_manager

    maker_addition = bytes32([101] * 32)
    taker_addition = bytes32([202] * 32)
    MAKER_ROWS.append(maker_addition)
    TAKER_ROWS.append(taker_addition)
    maker_root, maker_proofs = build_merkle_tree(MAKER_ROWS)
    taker_root, taker_proofs = build_merkle_tree(TAKER_ROWS)
    maker_branch, maker_branch_proof = get_parent_branch(maker_addition, maker_proofs[maker_addition])
    taker_branch, taker_branch_proof = get_parent_branch(taker_addition, taker_proofs[taker_addition])

    fee = uint64(2_000_000_000_000)

    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, offer_maker, error = await trade_manager_maker.create_offer_for_ids(
            {launcher_id_maker_1: -1, launcher_id_taker_1: 1, launcher_id_maker_2: -1, launcher_id_taker_2: 1},
            action_scope,
            solver=Solver(
                {
                    launcher_id_maker_1.hex(): {
                        "new_root": "0x" + maker_root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + launcher_id_taker_1.hex(),
                                "values_to_prove": ["0x" + taker_branch.hex(), "0x" + taker_branch.hex()],
                            }
                        ],
                    },
                    launcher_id_maker_2.hex(): {
                        "new_root": "0x" + maker_root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + launcher_id_taker_1.hex(),
                                "values_to_prove": ["0x" + taker_branch.hex()],
                            },
                            {
                                "launcher_id": "0x" + launcher_id_taker_2.hex(),
                                "values_to_prove": ["0x" + taker_branch.hex()],
                            },
                        ],
                    },
                }
            ),
            fee=fee,
        )
    assert error is None
    assert success is True
    assert offer_maker is not None

    [_maker_offer], signing_response = await wsm_maker.sign_offers([Offer.from_bytes(offer_maker.offer)])
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        offer_taker = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(offer_maker.offer),
            peer,
            action_scope,
            solver=Solver(
                {
                    launcher_id_taker_1.hex(): {
                        "new_root": "0x" + taker_root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + launcher_id_maker_1.hex(),
                                "values_to_prove": ["0x" + maker_branch.hex(), "0x" + maker_branch.hex()],
                            }
                        ],
                    },
                    launcher_id_taker_2.hex(): {
                        "new_root": "0x" + taker_root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + launcher_id_maker_1.hex(),
                                "values_to_prove": ["0x" + maker_branch.hex()],
                            },
                            {
                                "launcher_id": "0x" + launcher_id_maker_2.hex(),
                                "values_to_prove": ["0x" + maker_branch.hex()],
                            },
                        ],
                    },
                    "proofs_of_inclusion": [
                        [
                            maker_root.hex(),
                            str(maker_branch_proof[0]),
                            ["0x" + sibling.hex() for sibling in maker_branch_proof[1]],
                        ],
                        [
                            taker_root.hex(),
                            str(taker_branch_proof[0]),
                            ["0x" + sibling.hex() for sibling in taker_branch_proof[1]],
                        ],
                    ],
                }
            ),
            fee=fee,
        )
    assert offer_taker is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "spendable_balance": -fee,
                        "max_send_amount": -fee,
                        "pending_coin_removal_count": 2,
                    },
                    "dl": {
                        "pending_coin_removal_count": 2,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "confirmed_wallet_balance": -fee,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -2,
                    },
                    "dl": {
                        "pending_coin_removal_count": -2,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "spendable_balance": -fee,
                        "max_send_amount": -fee,
                        "pending_coin_removal_count": 2,
                    },
                    "dl": {
                        "pending_coin_removal_count": 4,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -2,
                    },
                    "dl": {
                        "pending_coin_removal_count": -4,
                    },
                },
            ),
        ]
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker_1, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker_2, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker_1, maker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker_2, maker_root)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, offer_maker)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, offer_taker)
