from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
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


def get_parent_branch(value: bytes32, proof: Tuple[int, List[bytes32]]) -> Tuple[bytes32, Tuple[int, List[bytes32]]]:
    branch: bytes32 = simplify_merkle_proof(value, (proof[0], [proof[1][0]]))
    new_proof: Tuple[int, List[bytes32]] = (proof[0] >> 1, proof[1][1:])
    return branch, new_proof


@pytest.mark.parametrize(
    "wallets_prefarm",
    [5],
    indirect=["wallets_prefarm"],
)
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dl_offers(wallets_prefarm: Any, trusted: bool) -> None:
    (
        [wallet_node_maker, maker_funds],
        [wallet_node_taker, taker_funds],
        full_node_api,
    ) = wallets_prefarm
    assert wallet_node_maker.wallet_state_manager is not None
    assert wallet_node_taker.wallet_state_manager is not None
    wsm_maker = wallet_node_maker.wallet_state_manager
    wsm_taker = wallet_node_taker.wallet_state_manager

    wallet_maker = wsm_maker.main_wallet
    wallet_taker = wsm_taker.main_wallet

    async with wsm_maker.lock:
        dl_wallet_maker = await DataLayerWallet.create_new_dl_wallet(wsm_maker, wallet_maker)
    async with wsm_taker.lock:
        dl_wallet_taker = await DataLayerWallet.create_new_dl_wallet(wsm_taker, wallet_taker)

    MAKER_ROWS = [bytes32([i] * 32) for i in range(0, 10)]
    TAKER_ROWS = [bytes32([i] * 32) for i in range(0, 10)]
    maker_root, _ = build_merkle_tree(MAKER_ROWS)
    taker_root, _ = build_merkle_tree(TAKER_ROWS)

    fee = uint64(1_999_999_999_999)

    dl_record, std_record, launcher_id_maker = await dl_wallet_maker.generate_new_reporter(maker_root, fee=fee)
    assert await dl_wallet_maker.get_latest_singleton(launcher_id_maker) is not None
    await wsm_maker.add_pending_transaction(dl_record)
    await wsm_maker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    maker_funds -= fee
    maker_funds -= 1
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_maker, maker_root)

    dl_record, std_record, launcher_id_taker = await dl_wallet_taker.generate_new_reporter(taker_root, fee=fee)
    assert await dl_wallet_taker.get_latest_singleton(launcher_id_taker) is not None
    await wsm_taker.add_pending_transaction(dl_record)
    await wsm_taker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    taker_funds -= fee
    taker_funds -= 1
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_taker, taker_root)

    peer = wallet_node_taker.get_full_node_peer()
    assert peer is not None
    await dl_wallet_maker.track_new_launcher_id(launcher_id_taker, peer)
    await dl_wallet_taker.track_new_launcher_id(launcher_id_maker, peer)
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

    # First test update <-> update
    success, offer_maker, error = await trade_manager_maker.create_offer_for_ids(
        {launcher_id_maker: -1, launcher_id_taker: 1},
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

    offer_taker, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(offer_maker.offer),
        peer,
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
    assert tx_records is not None

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

    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, maker_funds)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, taker_funds - fee)

    await full_node_api.process_transaction_records(records=tx_records)
    maker_funds -= fee
    taker_funds -= fee

    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)
    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, maker_funds)
    await time_out_assert(15, wallet_taker.get_confirmed_balance, taker_funds)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, taker_funds)

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

    # Now let's test payment <-> update
    # First XCH
    success, offer_maker, error = await trade_manager_maker.create_offer_for_ids(
        {1: -1, launcher_id_taker: 1},
        solver=Solver(
            {
                "": {
                    "dependencies": [
                        {
                            "launcher_id": "0x" + launcher_id_taker.hex(),
                            "values_to_prove": ["0x" + taker_branch.hex()],
                        },
                    ],
                },
                "bundle_actions": [
                    {
                        "type": "request_payment",
                        "asset_types": [],
                        "payments": [
                            {
                                "puzhash": "0x"
                                + (await wallet_node_maker.wallet_state_manager.main_wallet.get_new_puzzlehash()).hex(),
                                "amount": "1000000",
                                "memos": ["0xcafef00d"],
                            }
                        ],
                    },
                ],
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
                "asset_types": [],
                "amount": "1",
                "dependencies": [
                    {
                        "launcher_id": launcher_id_taker.hex(),
                        "values_to_prove": [taker_branch.hex()],
                    }
                ],
            }
        ],
        "requested": [{"asset_types": [], "amount": "1000000"}],
    }

    offer_taker, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(offer_maker.offer),
        peer,
        solver=Solver(
            {
                launcher_id_taker.hex(): {
                    "new_root": "0x" + taker_root.hex(),
                },
                "proofs_of_inclusion": [
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
    assert tx_records is not None

    assert await trade_manager_maker.get_offer_summary(Offer.from_bytes(offer_taker.offer)) == {
        "offered": [
            {
                "asset_types": [],
                "amount": "1000001",
                "dependencies": [
                    {
                        "launcher_id": launcher_id_taker.hex(),
                        "values_to_prove": [taker_branch.hex()],
                    }
                ],
            },
            {
                "asset_types": [
                    {
                        "mod": "(a (q 2 (i (logand 47 52) (q 4 (c 32 (c 47 ())) (c (a 62 (c 2 (c 5 (c (a 42 (c 2 (c 39 (c (a (i 119 (q 2 54 (c 2 (c 9 (c 87 (c (a 46 (c 2 (c 5 ()))) ()))))) (q . 29)) 1) (c (a (i 119 (q . -73) (q . 87)) 1) ()))))) (c 119 ()))))) (a 58 (c 2 (c 5 (c (a 11 95) (q ()))))))) (q 8)) 1) (c (q (((73 . 71) 2 . 51) (c . 1) 1 . 2) ((not 2 (i 5 (q 2 50 (c 2 (c 13 (c (sha256 60 (sha256 52 36) (sha256 60 (sha256 60 (sha256 52 44) 9) (sha256 60 11 (sha256 52 ())))) ())))) (q . 11)) 1) (a (i (all (= (strlen 5) 34) (= (strlen 11) 34) (> 23 (q . -1))) (q 11 5 11 23) (q 8)) 1) 2 (i 11 (q 2 (i (a 38 (c 2 (c 19 ()))) (q 2 (i (not 23) (q 2 (i (= -77 (q . -113)) (q 2 58 (c 2 (c 5 (c 27 (c 52 ()))))) (q 4 (c 35 (c (a 54 (c 2 (c 9 (c 83 (c (a 46 (c 2 (c 5 ()))) ()))))) 115)) (a 58 (c 2 (c 5 (c 27 (c 52 ()))))))) 1) (q 8)) 1) (q 4 19 (a 58 (c 2 (c 5 (c 27 (c 23 ()))))))) 1) (q 2 (i 23 () (q 8)) 1)) 1) ((a (i (= 9 56) (q 2 (i (logand 45 (q . 1)) (q 1 . 1) ()) 1) ()) 1) 11 60 (sha256 52 40) (sha256 60 (sha256 60 (sha256 52 44) 5) (sha256 60 (a 50 (c 2 (c 7 (c (sha256 52 52) ())))) (sha256 52 ())))) (a (i (l 5) (q 11 (q . 2) (a 46 (c 2 (c 9 ()))) (a 46 (c 2 (c 13 ())))) (q 11 (q . 1) 5)) 1) 2 (i (any 23 (= 11 21)) (q 4 48 (c 11 ())) (q 8)) 1) 1))",  # noqa
                        "solution_template": "((1 . (1 . 1)) 0 . $)",
                        "committed_args": f"((0x7faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9f . ({'0x' + launcher_id_taker.hex()} . 0xeff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9)) () . ())",  # noqa
                    },
                    {
                        "mod": "(a (q 2 62 (c 2 (c 5 (c (a 47 95) (c () (c (c (c 11 (c 23 ())) (q ())) (q ()))))))) (c (q ((a . 51) 4 1 . 1) (a 2 (i 5 (q 2 26 (c 2 (c 13 (c (sha256 18 (sha256 44 20) (sha256 18 (sha256 18 (sha256 44 60) 9) (sha256 18 11 (sha256 44 ())))) ())))) (q . 11)) 1) (sha256 18 (sha256 44 16) (sha256 18 (sha256 18 (sha256 44 60) 5) (sha256 18 (a 26 (c 2 (c 7 (c (sha256 44 44) ())))) (sha256 44 ())))) (a (i (l 5) (q 11 (q . 2) (a 46 (c 2 (c 9 ()))) (a 46 (c 2 (c 13 ())))) (q 11 (q . 1) 5)) 1) 2 (i 11 (q 2 (i (= 35 24) (q 2 (i (logand -77 44) (q 2 (i (not 23) (q 2 62 (c 2 (c 5 (c 27 (c 51 (c 47 (c 95 ()))))))) (q 8)) 1) (q 4 19 (a 62 (c 2 (c 5 (c 27 (c 23 (c 47 (c 95 ()))))))))) 1) (q 2 (i (= 35 (q . -24)) (q 2 62 (c 2 (c 5 (c 27 (c 23 (c (a (i (all (= (a 46 (c 2 (c 83 ()))) 335) (not 95)) (q 2 83 (c -113 (c 335 (c -77 ())))) (q 8)) 1) (c 44 ()))))))) (q 4 19 (a 62 (c 2 (c 5 (c 27 (c 23 (c 47 (c 95 ()))))))))) 1)) 1) (q 4 (c 24 (c (a 22 (c 2 (c 5 (c 39 (c (sha256 44 335) (c (a 46 (c 2 (c -113 ()))) (c (sha256 44 5) ()))))))) 55)) -81)) 1) 1))",  # noqa
                        "solution_template": "(1 1 1 0 . $)",
                        "committed_args": f"(0xa04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2 ({'0x' + taker_root.hex()}) 0x57bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9 () . ())",  # noqa
                    },
                ],
                "new_root": "0x" + taker_root.hex(),
            },
        ],
        "requested": [{"asset_types": [], "amount": "1000001"}],
    }

    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, maker_funds)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, taker_funds - fee - 1000000 + 1)

    await full_node_api.process_transaction_records(records=tx_records)
    maker_funds -= fee
    taker_funds -= fee

    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds - 1 + 1000000)
    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, maker_funds - 1 + 1000000)
    await time_out_assert(15, wallet_taker.get_confirmed_balance, taker_funds - 1000000 + 1)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, taker_funds - 1000000 + 1)

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker, maker_root)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, offer_maker)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, offer_taker)

    await time_out_assert(15, is_singleton_generation, True, dl_wallet_taker, launcher_id_taker, 4)

    txs = await dl_wallet_taker.create_update_state_spend(launcher_id_taker, bytes32([2] * 32))
    for tx in txs:
        await wallet_node_taker.wallet_state_manager.add_pending_transaction(tx)
    await full_node_api.process_transaction_records(records=txs)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dl_offer_cancellation(wallets_prefarm: Any, trusted: bool) -> None:
    [wallet_node, _], [_, _], full_node_api = wallets_prefarm
    assert wallet_node.wallet_state_manager is not None
    wsm = wallet_node.wallet_state_manager

    wallet = wsm.main_wallet

    async with wsm.lock:
        dl_wallet = await DataLayerWallet.create_new_dl_wallet(wsm, wallet)

    ROWS = [bytes32([i] * 32) for i in range(0, 10)]
    root, _ = build_merkle_tree(ROWS)

    dl_record, std_record, launcher_id = await dl_wallet.generate_new_reporter(root)
    assert await dl_wallet.get_latest_singleton(launcher_id) is not None
    await wsm.add_pending_transaction(dl_record)
    await wsm.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, root)
    dl_record_2, std_record_2, launcher_id_2 = await dl_wallet.generate_new_reporter(root)
    await wsm.add_pending_transaction(dl_record_2)
    await wsm.add_pending_transaction(std_record_2)
    await full_node_api.process_transaction_records(records=[dl_record_2, std_record_2])

    trade_manager = wsm.trade_manager

    addition = bytes32([101] * 32)
    ROWS.append(addition)
    root, proofs = build_merkle_tree(ROWS)

    success, offer, error = await trade_manager.create_offer_for_ids(
        {launcher_id: -1, launcher_id_2: 1},
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
        fee=uint64(2_000_000_000_000),
    )
    assert error is None
    assert success is True
    assert offer is not None

    cancellation_txs = await trade_manager.cancel_pending_offer_safely(offer.trade_id, fee=uint64(2_000_000_000_000))
    assert len(cancellation_txs) == 3
    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager, offer)
    await full_node_api.process_transaction_records(records=cancellation_txs)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager, offer)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_multiple_dl_offers(wallets_prefarm: Any, trusted: bool) -> None:
    (
        [wallet_node_maker, maker_funds],
        [wallet_node_taker, taker_funds],
        full_node_api,
    ) = wallets_prefarm
    assert wallet_node_maker.wallet_state_manager is not None
    assert wallet_node_taker.wallet_state_manager is not None
    wsm_maker = wallet_node_maker.wallet_state_manager
    wsm_taker = wallet_node_taker.wallet_state_manager

    wallet_maker = wsm_maker.main_wallet
    wallet_taker = wsm_taker.main_wallet

    async with wsm_maker.lock:
        dl_wallet_maker = await DataLayerWallet.create_new_dl_wallet(wsm_maker, wallet_maker)
    async with wsm_taker.lock:
        dl_wallet_taker = await DataLayerWallet.create_new_dl_wallet(wsm_taker, wallet_taker)

    MAKER_ROWS = [bytes32([i] * 32) for i in range(0, 10)]
    TAKER_ROWS = [bytes32([i] * 32) for i in range(10, 20)]
    maker_root, _ = build_merkle_tree(MAKER_ROWS)
    taker_root, _ = build_merkle_tree(TAKER_ROWS)

    fee = uint64(1_999_999_999_999)

    dl_record, std_record, launcher_id_maker_1 = await dl_wallet_maker.generate_new_reporter(maker_root, fee=fee)
    assert await dl_wallet_maker.get_latest_singleton(launcher_id_maker_1) is not None
    await wsm_maker.add_pending_transaction(dl_record)
    await wsm_maker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    maker_funds -= fee
    maker_funds -= 1
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_maker_1, maker_root)
    dl_record, std_record, launcher_id_maker_2 = await dl_wallet_maker.generate_new_reporter(maker_root, fee=fee)
    assert await dl_wallet_maker.get_latest_singleton(launcher_id_maker_2) is not None
    await wsm_maker.add_pending_transaction(dl_record)
    await wsm_maker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    maker_funds -= fee
    maker_funds -= 1
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_maker_2, maker_root)

    dl_record, std_record, launcher_id_taker_1 = await dl_wallet_taker.generate_new_reporter(taker_root, fee=fee)
    assert await dl_wallet_taker.get_latest_singleton(launcher_id_taker_1) is not None
    await wsm_taker.add_pending_transaction(dl_record)
    await wsm_taker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    taker_funds -= fee
    taker_funds -= 1
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_taker_1, taker_root)
    dl_record, std_record, launcher_id_taker_2 = await dl_wallet_taker.generate_new_reporter(taker_root, fee=fee)
    assert await dl_wallet_taker.get_latest_singleton(launcher_id_taker_2) is not None
    await wsm_taker.add_pending_transaction(dl_record)
    await wsm_taker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    taker_funds -= fee
    taker_funds -= 1
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_taker_2, taker_root)

    peer = wallet_node_taker.get_full_node_peer()
    assert peer is not None
    await dl_wallet_maker.track_new_launcher_id(launcher_id_taker_1, peer)
    await dl_wallet_maker.track_new_launcher_id(launcher_id_taker_2, peer)
    await dl_wallet_taker.track_new_launcher_id(launcher_id_maker_1, peer)
    await dl_wallet_taker.track_new_launcher_id(launcher_id_maker_2, peer)
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

    success, offer_maker, error = await trade_manager_maker.create_offer_for_ids(
        {launcher_id_maker_1: -1, launcher_id_taker_1: 1, launcher_id_maker_2: -1, launcher_id_taker_2: 1},
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

    offer_taker, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(offer_maker.offer),
        peer,
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
    assert tx_records is not None

    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, maker_funds)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, taker_funds - fee)

    await full_node_api.process_transaction_records(records=tx_records)

    maker_funds -= fee
    taker_funds -= fee

    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)
    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, maker_funds)
    await time_out_assert(15, wallet_taker.get_confirmed_balance, taker_funds)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, taker_funds)

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker_1, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_maker, launcher_id_taker_2, taker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker_1, maker_root)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_taker, launcher_id_maker_2, maker_root)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, offer_maker)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, offer_taker)
