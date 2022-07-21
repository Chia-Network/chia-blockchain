import dataclasses
from typing import Any, List, Tuple

import pytest

from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzle_drivers import Solver
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trade_record import TradeRecord
from chia.wallet.util.merkle_utils import build_merkle_tree
from tests.time_out_assert import time_out_assert


async def is_singleton_confirmed(dl_wallet: DataLayerWallet, lid: bytes32) -> bool:
    rec = await dl_wallet.get_latest_singleton(lid)
    if rec is None:
        return False
    if rec.confirmed is True:
        assert rec.confirmed_at_height > 0
        assert rec.timestamp > 0
    return rec.confirmed


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dl_offers(wallets_prefarm: Any, trusted: bool) -> None:
    wallet_node_maker, wallet_node_taker, full_node_api = wallets_prefarm
    assert wallet_node_maker.wallet_state_manager is not None
    assert wallet_node_taker.wallet_state_manager is not None
    wsm_maker = wallet_node_maker.wallet_state_manager
    wsm_taker = wallet_node_taker.wallet_state_manager

    wallet_maker = wsm_maker.main_wallet
    wallet_taker = wsm_taker.main_wallet

    funds = 20000000000000

    await time_out_assert(10, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(10, wallet_taker.get_confirmed_balance, funds)

    async with wsm_maker.lock:
        dl_wallet_maker = await DataLayerWallet.create_new_dl_wallet(wsm_maker, wallet_maker)
    async with wsm_taker.lock:
        dl_wallet_taker = await DataLayerWallet.create_new_dl_wallet(wsm_taker, wallet_taker)

    MAKER_ROWS = [bytes32([i] * 32) for i in range(0, 10)]
    TAKER_ROWS = [bytes32([i] * 32) for i in range(10, 20)]
    maker_root, _ = build_merkle_tree(MAKER_ROWS)
    taker_root, _ = build_merkle_tree(TAKER_ROWS)

    dl_record, std_record, launcher_id_maker = await dl_wallet_maker.generate_new_reporter(
        maker_root, fee=uint64(1999999999999)
    )
    assert await dl_wallet_maker.get_latest_singleton(launcher_id_maker) is not None
    await wsm_maker.add_pending_transaction(dl_record)
    await wsm_maker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_maker, launcher_id_maker)

    dl_record, std_record, launcher_id_taker = await dl_wallet_taker.generate_new_reporter(
        taker_root, fee=uint64(1999999999999)
    )
    assert await dl_wallet_taker.get_latest_singleton(launcher_id_taker) is not None
    await wsm_taker.add_pending_transaction(dl_record)
    await wsm_taker.add_pending_transaction(std_record)
    await full_node_api.process_transaction_records(records=[dl_record, std_record])
    await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_taker, launcher_id_taker)

    await dl_wallet_maker.track_new_launcher_id(launcher_id_taker)
    await dl_wallet_taker.track_new_launcher_id(launcher_id_maker)
    await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_maker, launcher_id_taker)
    await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_taker, launcher_id_maker)

    trade_manager_maker = wsm_maker.trade_manager
    trade_manager_taker = wsm_taker.trade_manager

    maker_addition = bytes32([101] * 32)
    taker_addition = bytes32([202] * 32)
    MAKER_ROWS.append(maker_addition)
    TAKER_ROWS.append(taker_addition)
    maker_root, maker_proofs = build_merkle_tree(MAKER_ROWS)
    taker_root, taker_proofs = build_merkle_tree(TAKER_ROWS)

    success, offer_maker, error = await trade_manager_maker.create_offer_for_ids(
        {launcher_id_maker: -1, launcher_id_taker: 1},
        solver=Solver(
            {
                launcher_id_maker.hex(): {
                    "new_root": "0x" + maker_root.hex(),
                    "dependencies": {
                        launcher_id_taker.hex(): ["0x" + taker_addition.hex()],
                    },
                }
            }
        ),
        fee=uint64(2000000000000),
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
                        "values_to_prove": [taker_addition.hex()],
                    }
                ],
            }
        ]
    }

    maker_proof: Tuple[int, List[bytes32]] = maker_proofs[maker_addition]
    taker_proof: Tuple[int, List[bytes32]] = taker_proofs[taker_addition]
    success, offer_taker, error = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(offer_maker.offer),
        solver=Solver(
            {
                launcher_id_taker.hex(): {
                    "new_root": "0x" + taker_root.hex(),
                    "dependencies": {
                        launcher_id_maker.hex(): ["0x" + maker_addition.hex()],
                    },
                },
                "proofs_of_inclusion": {
                    maker_root.hex(): [str(maker_proof[0]), ["0x" + sibling.hex() for sibling in maker_proof[1]]],
                    taker_root.hex(): [str(taker_proof[0]), ["0x" + sibling.hex() for sibling in taker_proof[1]]],
                },
            }
        ),
        fee=uint64(2000000000000),
    )
    assert error is None
    assert success is True
    assert offer_taker is not None

    assert await trade_manager_maker.get_offer_summary(Offer.from_bytes(offer_taker.offer)) == {
        "offered": [
            {
                "launcher_id": launcher_id_maker.hex(),
                "new_root": maker_root.hex(),
                "dependencies": [
                    {
                        "launcher_id": launcher_id_taker.hex(),
                        "values_to_prove": [taker_addition.hex()],
                    }
                ],
            },
            {
                "launcher_id": launcher_id_taker.hex(),
                "new_root": taker_root.hex(),
                "dependencies": [
                    {
                        "launcher_id": launcher_id_maker.hex(),
                        "values_to_prove": [maker_addition.hex()],
                    }
                ],
            },
        ]
    }

    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, funds - 2000000000000)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, funds - 4000000000000)

    # Let's hack a way to await this offer's confirmation
    offer_record = dataclasses.replace(dl_record, spend_bundle=Offer.from_bytes(offer_taker.offer).bundle)
    await full_node_api.process_transaction_records(records=[offer_record])

    await time_out_assert(15, wallet_maker.get_confirmed_balance, funds - 4000000000000)
    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, funds - 4000000000000)
    await time_out_assert(15, wallet_taker.get_confirmed_balance, funds - 4000000000000)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, funds - 4000000000000)

    maker_singleton = await dl_wallet_maker.get_latest_singleton(launcher_id_maker)
    taker_singleton = await dl_wallet_taker.get_latest_singleton(launcher_id_taker)
    assert maker_singleton is not None
    assert taker_singleton is not None
    assert maker_singleton.root == maker_root
    assert taker_singleton.root == taker_root

    async def get_trade_and_status(trade_manager: Any, trade: TradeRecord) -> TradeStatus:
        trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
        return TradeStatus(trade_rec.status)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, offer_maker)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, offer_taker)
