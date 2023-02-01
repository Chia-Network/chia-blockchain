from __future__ import annotations

import asyncio
from dataclasses import replace
from secrets import token_bytes
from typing import Any, Dict, List

import pytest

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import INFINITE_COST
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from tests.util.wallet_is_synced import wallets_are_synced

buffer_blocks = 4


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
class TestCATTrades:
    @pytest.mark.asyncio
    async def test_cat_trades(self, wallets_prefarm):
        (
            [wallet_node_maker, initial_maker_balance],
            [wallet_node_taker, initial_taker_balance],
            full_node,
        ) = wallets_prefarm
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
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, 100)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, 100)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, 100)

        # Add the taker's CAT to the maker's wallet
        assert cat_wallet_maker.cat_info.my_tail is not None
        assert new_cat_wallet_taker.cat_info.my_tail is not None
        new_cat_wallet_maker: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
            wallet_node_maker.wallet_state_manager, wallet_maker, new_cat_wallet_taker.get_asset_id()
        )

        # Create the trade parameters
        MAKER_CHIA_BALANCE = initial_maker_balance - 100
        TAKER_CHIA_BALANCE = initial_taker_balance - 100
        await time_out_assert(25, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(25, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        MAKER_CAT_BALANCE = 100
        MAKER_NEW_CAT_BALANCE = 0
        TAKER_CAT_BALANCE = 0
        TAKER_NEW_CAT_BALANCE = 100

        chia_for_cat = {
            wallet_maker.id(): -1,
            bytes.fromhex(new_cat_wallet_maker.get_asset_id()): 2,  # This is the CAT that the taker made
        }
        cat_for_chia = {
            wallet_maker.id(): 3,
            cat_wallet_maker.id(): -4,  # The taker has no knowledge of this CAT yet
        }
        cat_for_cat = {
            bytes.fromhex(cat_wallet_maker.get_asset_id()): -5,
            new_cat_wallet_maker.id(): 6,
        }
        chia_for_multiple_cat = {
            wallet_maker.id(): -7,
            cat_wallet_maker.id(): 8,
            new_cat_wallet_maker.id(): 9,
        }
        multiple_cat_for_chia = {
            wallet_maker.id(): 10,
            cat_wallet_maker.id(): -11,
            new_cat_wallet_maker.id(): -12,
        }
        chia_and_cat_for_cat = {
            wallet_maker.id(): -13,
            cat_wallet_maker.id(): -14,
            new_cat_wallet_maker.id(): 15,
        }

        driver_dict: Dict[str, Dict[str, Any]] = {}
        for wallet in (cat_wallet_maker, new_cat_wallet_maker):
            asset_id: str = wallet.get_asset_id()
            driver_dict[bytes.fromhex(asset_id)] = PuzzleInfo(
                {
                    "type": AssetType.CAT.name,
                    "tail": "0x" + asset_id,
                }
            )

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
        trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

        # Execute all of the trades
        old_maker_offer = Offer.from_bytes(bytes.fromhex("0000000200000000000000000000000000000000000000000000000000000000000000008e724dc57c44ef0247e6d9e4b045304cc06d1b0205bc90bc2d5953e1f63631690000000000000000ff02ffff01ff02ffff01ff02ff5effff04ff02ffff04ffff04ff05ffff04ffff0bff34ff0580ffff04ff0bff80808080ffff04ffff02ff17ff2f80ffff04ff5fffff04ffff02ff2effff04ff02ffff04ff17ff80808080ffff04ffff02ff2affff04ff02ffff04ff82027fffff04ff82057fffff04ff820b7fff808080808080ffff04ff81bfffff04ff82017fffff04ff8202ffffff04ff8205ffffff04ff820bffff80808080808080808080808080ffff04ffff01ffffffff3d46ff02ff333cffff0401ff01ff81cb02ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff7cffff0bff34ff2480ffff0bff7cffff0bff7cffff0bff34ff2c80ff0980ffff0bff7cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ffff02ffff03ff0bffff01ff02ffff03ffff09ffff02ff2effff04ff02ffff04ff13ff80808080ff820b9f80ffff01ff02ff56ffff04ff02ffff04ffff02ff13ffff04ff5fffff04ff17ffff04ff2fffff04ff81bfffff04ff82017fffff04ff1bff8080808080808080ffff04ff82017fff8080808080ffff01ff088080ff0180ffff01ff02ffff03ff17ffff01ff02ffff03ffff20ff81bf80ffff0182017fffff01ff088080ff0180ffff01ff088080ff018080ff0180ff04ffff04ff05ff2780ffff04ffff10ff0bff5780ff778080ffffff02ffff03ff05ffff01ff02ffff03ffff09ffff02ffff03ffff09ff11ff5880ffff0159ff8080ff0180ffff01818f80ffff01ff02ff26ffff04ff02ffff04ff0dffff04ff0bffff04ffff04ff81b9ff82017980ff808080808080ffff01ff02ff7affff04ff02ffff04ffff02ffff03ffff09ff11ff5880ffff01ff04ff58ffff04ffff02ff76ffff04ff02ffff04ff13ffff04ff29ffff04ffff0bff34ff5b80ffff04ff2bff80808080808080ff398080ffff01ff02ffff03ffff09ff11ff7880ffff01ff02ffff03ffff20ffff02ffff03ffff09ffff0121ffff0dff298080ffff01ff02ffff03ffff09ffff0cff29ff80ff3480ff5c80ffff01ff0101ff8080ff0180ff8080ff018080ffff0109ffff01ff088080ff0180ffff010980ff018080ff0180ffff04ffff02ffff03ffff09ff11ff5880ffff0159ff8080ff0180ffff04ffff02ff26ffff04ff02ffff04ff0dffff04ff0bffff04ff17ff808080808080ff80808080808080ff0180ffff01ff04ff80ffff04ff80ff17808080ff0180ffff02ffff03ff05ffff01ff04ff09ffff02ff56ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff010b80ff0180ff0bff7cffff0bff34ff2880ffff0bff7cffff0bff7cffff0bff34ff2c80ff0580ffff0bff7cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff04ffff04ff30ffff04ff5fff808080ffff02ff7effff04ff02ffff04ffff04ffff04ff2fff0580ffff04ff5fff82017f8080ffff04ffff02ff26ffff04ff02ffff04ff0bffff04ff05ffff01ff808080808080ffff04ff17ffff04ff81bfffff04ff82017fffff04ffff02ff2affff04ff02ffff04ff8204ffffff04ffff02ff76ffff04ff02ffff04ff09ffff04ff820affffff04ffff0bff34ff2d80ffff04ff15ff80808080808080ffff04ff8216ffff808080808080ffff04ff8205ffffff04ff820bffff808080808080808080808080ff02ff5affff04ff02ffff04ff5fffff04ff3bffff04ffff02ffff03ff17ffff01ff09ff2dffff02ff2affff04ff02ffff04ff27ffff04ffff02ff76ffff04ff02ffff04ff29ffff04ff57ffff04ffff0bff34ff81b980ffff04ff59ff80808080808080ffff04ff81b7ff80808080808080ff8080ff0180ffff04ff17ffff04ff05ffff04ff8202ffffff04ffff04ffff04ff78ffff04ffff0eff5cffff02ff2effff04ff02ffff04ffff04ff2fffff04ff82017fff808080ff8080808080ff808080ffff04ffff04ff20ffff04ffff0bff81bfff5cffff02ff2effff04ff02ffff04ffff04ff15ffff04ffff10ff82017fffff11ff8202dfff2b80ff8202ff80ff808080ff8080808080ff808080ff138080ff80808080808080808080ff018080ffff04ffff01a037bef360ee858133b69d595a906dc45d01af50379dad515eb9518abb7c1d2a7affff04ffff01a0b2847c2a1428be2af434b78ab85b08c46f13cb4dfd686ac21e7ee484504bebacffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff0180808080ffffa05dd3364e78b4362d07eb167bd9777a27198ea20f2d365a8b99d1f7ee9480678cffffa066f9d0199a23435445559963348176a0f30cd62bb94e39076478947da01fae2aff02ffffa066f9d0199a23435445559963348176a0f30cd62bb94e39076478947da01fae2a808080809563629e653a9fc3c65f55947883a47e062e6b67394091228ec01352ff78f333e4fb5940aef16e2c6cfed28ea3934dada96f4ce2b629b17cd482eb31f6a6c5590000003a3529439cff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b080399dec21ec7ab66ed0b43811652c2c27c16e2f304b8e2900d7f510448675ef9d8be70ba19e6b6675c4d9bb5f75ced4ff018080ff80ffff01ffff33ffa0bae24162efbd568f89bc7a340798a6118df0189eb9e3f8697bcea27af99f8f79ff0180ffff33ffa0846b58db3bd246785e202eeddfbb46acaf267f011307437cd4e0841f3da751f6ff853a3529439a80ffff34ff0180ffff3cffa0ec3b67cd6f44441d032e61df625b5d2cd7a68723fac63c63519f67e2441bf83f80ffff3fffa03926f78396e6fb73243eeb599c8622bb79cd9c896b762fafd61c3afa23d7676f8080ff8080b709a8b602665d0605d41f8d06b63aff4ea8dffde4ef8ef365cd779095d06d3a875120cb43f8eba83233ff8d872400c71616dcf0eb7baafdf36950b8424ab9264984847eeea3bcd5799c0c0be601464d56432ef0461ca6c93d82386928fb05d6"))
        # chia_for_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, fee=uint64(1))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None

        await trade_manager_maker.trade_store.add_trade_record(replace(trade_make, offer=bytes(old_maker_offer)))

        peer = wallet_node_taker.get_full_node_peer()
        assert peer is not None
        trade_take, tx_records = await trade_manager_taker.respond_to_offer(
            old_maker_offer, peer, fee=uint64(1)
        )
        assert trade_take is not None
        assert tx_records is not None

        first_offer = Offer.from_bytes(bytes.fromhex("000000050000000000000000000000000000000000000000000000000000000000000000131816d2ed127bfc4fcde644a6f46e764b9123a9d041b22726d35ab5ff13a19c0000000000000000ff02ffff01ff02ffff01ff02ff5effff04ff02ffff04ffff04ff05ffff04ffff0bff34ff0580ffff04ff0bff80808080ffff04ffff02ff17ff2f80ffff04ff5fffff04ffff02ff2effff04ff02ffff04ff17ff80808080ffff04ffff02ff2affff04ff02ffff04ff82027fffff04ff82057fffff04ff820b7fff808080808080ffff04ff81bfffff04ff82017fffff04ff8202ffffff04ff8205ffffff04ff820bffff80808080808080808080808080ffff04ffff01ffffffff3d46ff02ff333cffff0401ff01ff81cb02ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff7cffff0bff34ff2480ffff0bff7cffff0bff7cffff0bff34ff2c80ff0980ffff0bff7cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ffff02ffff03ff0bffff01ff02ffff03ffff09ffff02ff2effff04ff02ffff04ff13ff80808080ff820b9f80ffff01ff02ff56ffff04ff02ffff04ffff02ff13ffff04ff5fffff04ff17ffff04ff2fffff04ff81bfffff04ff82017fffff04ff1bff8080808080808080ffff04ff82017fff8080808080ffff01ff088080ff0180ffff01ff02ffff03ff17ffff01ff02ffff03ffff20ff81bf80ffff0182017fffff01ff088080ff0180ffff01ff088080ff018080ff0180ff04ffff04ff05ff2780ffff04ffff10ff0bff5780ff778080ffffff02ffff03ff05ffff01ff02ffff03ffff09ffff02ffff03ffff09ff11ff5880ffff0159ff8080ff0180ffff01818f80ffff01ff02ff26ffff04ff02ffff04ff0dffff04ff0bffff04ffff04ff81b9ff82017980ff808080808080ffff01ff02ff7affff04ff02ffff04ffff02ffff03ffff09ff11ff5880ffff01ff04ff58ffff04ffff02ff76ffff04ff02ffff04ff13ffff04ff29ffff04ffff0bff34ff5b80ffff04ff2bff80808080808080ff398080ffff01ff02ffff03ffff09ff11ff7880ffff01ff02ffff03ffff20ffff02ffff03ffff09ffff0121ffff0dff298080ffff01ff02ffff03ffff09ffff0cff29ff80ff3480ff5c80ffff01ff0101ff8080ff0180ff8080ff018080ffff0109ffff01ff088080ff0180ffff010980ff018080ff0180ffff04ffff02ffff03ffff09ff11ff5880ffff0159ff8080ff0180ffff04ffff02ff26ffff04ff02ffff04ff0dffff04ff0bffff04ff17ff808080808080ff80808080808080ff0180ffff01ff04ff80ffff04ff80ff17808080ff0180ffff02ffff03ff05ffff01ff04ff09ffff02ff56ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff010b80ff0180ff0bff7cffff0bff34ff2880ffff0bff7cffff0bff7cffff0bff34ff2c80ff0580ffff0bff7cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff04ffff04ff30ffff04ff5fff808080ffff02ff7effff04ff02ffff04ffff04ffff04ff2fff0580ffff04ff5fff82017f8080ffff04ffff02ff26ffff04ff02ffff04ff0bffff04ff05ffff01ff808080808080ffff04ff17ffff04ff81bfffff04ff82017fffff04ffff02ff2affff04ff02ffff04ff8204ffffff04ffff02ff76ffff04ff02ffff04ff09ffff04ff820affffff04ffff0bff34ff2d80ffff04ff15ff80808080808080ffff04ff8216ffff808080808080ffff04ff8205ffffff04ff820bffff808080808080808080808080ff02ff5affff04ff02ffff04ff5fffff04ff3bffff04ffff02ffff03ff17ffff01ff09ff2dffff02ff2affff04ff02ffff04ff27ffff04ffff02ff76ffff04ff02ffff04ff29ffff04ff57ffff04ffff0bff34ff81b980ffff04ff59ff80808080808080ffff04ff81b7ff80808080808080ff8080ff0180ffff04ff17ffff04ff05ffff04ff8202ffffff04ffff04ffff04ff78ffff04ffff0eff5cffff02ff2effff04ff02ffff04ffff04ff2fffff04ff82017fff808080ff8080808080ff808080ffff04ffff04ff20ffff04ffff0bff81bfff5cffff02ff2effff04ff02ffff04ffff04ff15ffff04ffff10ff82017fffff11ff8202dfff2b80ff8202ff80ff808080ff8080808080ff808080ff138080ff80808080808080808080ff018080ffff04ffff01a037bef360ee858133b69d595a906dc45d01af50379dad515eb9518abb7c1d2a7affff04ffff01a0b2847c2a1428be2af434b78ab85b08c46f13cb4dfd686ac21e7ee484504bebacffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff0180808080ffffa05dd3364e78b4362d07eb167bd9777a27198ea20f2d365a8b99d1f7ee9480678cffffa066f9d0199a23435445559963348176a0f30cd62bb94e39076478947da01fae2aff02ffffa066f9d0199a23435445559963348176a0f30cd62bb94e39076478947da01fae2a808080800000000000000000000000000000000000000000000000000000000000000000cfbfdeed5c4ca2de3d0bf520b9cb4bb7743a359bd2e6a188d19ce7dffc21d3e70000000000000000ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffffa0029457911f592c7b41905e7ff40c6db95307b0da9ea68c44c1714d2c5b7ff857ffffa00fa3e13a7049e58bfd56551a637610859a0cc51ffea9416ff3857c52b3f0f0f0ff01ff808080809563629e653a9fc3c65f55947883a47e062e6b67394091228ec01352ff78f333e4fb5940aef16e2c6cfed28ea3934dada96f4ce2b629b17cd482eb31f6a6c5590000003a3529439cff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b080399dec21ec7ab66ed0b43811652c2c27c16e2f304b8e2900d7f510448675ef9d8be70ba19e6b6675c4d9bb5f75ced4ff018080ff80ffff01ffff33ffa0cfbfdeed5c4ca2de3d0bf520b9cb4bb7743a359bd2e6a188d19ce7dffc21d3e7ff0180ffff33ffa0846b58db3bd246785e202eeddfbb46acaf267f011307437cd4e0841f3da751f6ff853a3529439a80ffff34ff0180ffff3cffa03bd023634d84aa11c1fac0829159a7be893c8902066fd144a0f6b128ac9c0d1e80ffff3fffa0fe7b6aec43c187bc90df28ee9c344992106c2b484140b8d14d424ca96cd553908080ff80804b3dbe3376b29f3d14062ae7450c27448902dbd7d01eee959d8e1a3725ac70e4240131d2d424812c8a4a9756209100da8b9f80081e098053b4e5348d13fbfaf40000000000000064ff02ffff01ff02ffff01ff02ff5effff04ff02ffff04ffff04ff05ffff04ffff0bff34ff0580ffff04ff0bff80808080ffff04ffff02ff17ff2f80ffff04ff5fffff04ffff02ff2effff04ff02ffff04ff17ff80808080ffff04ffff02ff2affff04ff02ffff04ff82027fffff04ff82057fffff04ff820b7fff808080808080ffff04ff81bfffff04ff82017fffff04ff8202ffffff04ff8205ffffff04ff820bffff80808080808080808080808080ffff04ffff01ffffffff3d46ff02ff333cffff0401ff01ff81cb02ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff7cffff0bff34ff2480ffff0bff7cffff0bff7cffff0bff34ff2c80ff0980ffff0bff7cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ffff02ffff03ff0bffff01ff02ffff03ffff09ffff02ff2effff04ff02ffff04ff13ff80808080ff820b9f80ffff01ff02ff56ffff04ff02ffff04ffff02ff13ffff04ff5fffff04ff17ffff04ff2fffff04ff81bfffff04ff82017fffff04ff1bff8080808080808080ffff04ff82017fff8080808080ffff01ff088080ff0180ffff01ff02ffff03ff17ffff01ff02ffff03ffff20ff81bf80ffff0182017fffff01ff088080ff0180ffff01ff088080ff018080ff0180ff04ffff04ff05ff2780ffff04ffff10ff0bff5780ff778080ffffff02ffff03ff05ffff01ff02ffff03ffff09ffff02ffff03ffff09ff11ff5880ffff0159ff8080ff0180ffff01818f80ffff01ff02ff26ffff04ff02ffff04ff0dffff04ff0bffff04ffff04ff81b9ff82017980ff808080808080ffff01ff02ff7affff04ff02ffff04ffff02ffff03ffff09ff11ff5880ffff01ff04ff58ffff04ffff02ff76ffff04ff02ffff04ff13ffff04ff29ffff04ffff0bff34ff5b80ffff04ff2bff80808080808080ff398080ffff01ff02ffff03ffff09ff11ff7880ffff01ff02ffff03ffff20ffff02ffff03ffff09ffff0121ffff0dff298080ffff01ff02ffff03ffff09ffff0cff29ff80ff3480ff5c80ffff01ff0101ff8080ff0180ff8080ff018080ffff0109ffff01ff088080ff0180ffff010980ff018080ff0180ffff04ffff02ffff03ffff09ff11ff5880ffff0159ff8080ff0180ffff04ffff02ff26ffff04ff02ffff04ff0dffff04ff0bffff04ff17ff808080808080ff80808080808080ff0180ffff01ff04ff80ffff04ff80ff17808080ff0180ffff02ffff03ff05ffff01ff04ff09ffff02ff56ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff010b80ff0180ff0bff7cffff0bff34ff2880ffff0bff7cffff0bff7cffff0bff34ff2c80ff0580ffff0bff7cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff04ffff04ff30ffff04ff5fff808080ffff02ff7effff04ff02ffff04ffff04ffff04ff2fff0580ffff04ff5fff82017f8080ffff04ffff02ff26ffff04ff02ffff04ff0bffff04ff05ffff01ff808080808080ffff04ff17ffff04ff81bfffff04ff82017fffff04ffff02ff2affff04ff02ffff04ff8204ffffff04ffff02ff76ffff04ff02ffff04ff09ffff04ff820affffff04ffff0bff34ff2d80ffff04ff15ff80808080808080ffff04ff8216ffff808080808080ffff04ff8205ffffff04ff820bffff808080808080808080808080ff02ff5affff04ff02ffff04ff5fffff04ff3bffff04ffff02ffff03ff17ffff01ff09ff2dffff02ff2affff04ff02ffff04ff27ffff04ffff02ff76ffff04ff02ffff04ff29ffff04ff57ffff04ffff0bff34ff81b980ffff04ff59ff80808080808080ffff04ff81b7ff80808080808080ff8080ff0180ffff04ff17ffff04ff05ffff04ff8202ffffff04ffff04ffff04ff78ffff04ffff0eff5cffff02ff2effff04ff02ffff04ffff04ff2fffff04ff82017fff808080ff8080808080ff808080ffff04ffff04ff20ffff04ffff0bff81bfff5cffff02ff2effff04ff02ffff04ffff04ff15ffff04ffff10ff82017fffff11ff8202dfff2b80ff8202ff80ff808080ff8080808080ff808080ff138080ff80808080808080808080ff018080ffff04ffff01a037bef360ee858133b69d595a906dc45d01af50379dad515eb9518abb7c1d2a7affff04ffff01a0b2847c2a1428be2af434b78ab85b08c46f13cb4dfd686ac21e7ee484504bebacffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a6c878d82fbd95f75e4ddfddb585d356ca350c66abd7e7fecd8de3742d0bef45bae59ac94285eef0bafa91941900a5d2ff018080ff0180808080ffff80ffff01ffff33ffa0cfbfdeed5c4ca2de3d0bf520b9cb4bb7743a359bd2e6a188d19ce7dffc21d3e7ff02ffffa0cfbfdeed5c4ca2de3d0bf520b9cb4bb7743a359bd2e6a188d19ce7dffc21d3e78080ffff33ffa0dfcf1b943c534c07079b1198a7eaf4b56cb06e1140655ff8019ef308f1f59c25ff6280ffff3cffa0253d152f54d761fc1760b443edb0dcf979d4b8167d2c2e4aada4685657942fa480ffff3fffa04c63934ae454e2efed62fec873289207b952badc3ee101ab8c996b97ebe229f88080ff8080ffffa0c8b24907a9f259144c45a36fc61177496d272167db2428a1b59e6a248597086cffa00532eb4ea071f8f965a9269ed6db179daf5f3799a27b0f9d218bfced3d58bffbff6480ffa050687dacfe142b76db5af3bc3bd197bd89c0287e7665e5925573fd4e672b23c5ffffa04b3dbe3376b29f3d14062ae7450c27448902dbd7d01eee959d8e1a3725ac70e4ffa0240131d2d424812c8a4a9756209100da8b9f80081e098053b4e5348d13fbfaf4ff6480ffffa04b3dbe3376b29f3d14062ae7450c27448902dbd7d01eee959d8e1a3725ac70e4ffa00532eb4ea071f8f965a9269ed6db179daf5f3799a27b0f9d218bfced3d58bffbff6480ff80ff8080c8b24907a9f259144c45a36fc61177496d272167db2428a1b59e6a248597086cba934771c8d2d08140a6bbe9a7508f192b64564bf30a054e3cf215224845dd5a0000003a3529439cff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b08595a83f106ce887c37b956bf828b8aafc677bff1b07e436843eb1201dde9120d0420634cb362ac2bcf8de6454917bf2ff018080ff80ffff01ffff33ffa066d8e1697a4c3ee4c0afe744d149f345d7b3be87fcfb191fa3f106b2021fc7edff853a3529439b80ffff34ff0180ffff3cffa0b7bf90130415e5d8c4e79f4e01468f8df41b2c93af1e2ba57a00693c9328dd2c80ffff3dffa03f89b02b428b0199ba475cbf9e9e66eaaa6d751c424d720349e82f8d3cfba7258080ff8080b0cdb1eedcfa5e44fcc6983107af90e70a3f89642cefeb514ee045bf1a4a2644ac6dfae7a7f5721643b1c2dafeec537c0e20cf2ca4f1e0c8b08fb5362277895220d8ac744cb737b4901941ba6b3ecdb23004f7bff4ad57f7416d72bd069b268a"))

        MAKER_CHIA_BALANCE -= 2  # -1 and -1 for fee
        MAKER_NEW_CAT_BALANCE += 2
        TAKER_CHIA_BALANCE += 0  # +1 and -1 for fee
        TAKER_NEW_CAT_BALANCE -= 2

        await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)

        await full_node.process_transaction_records(records=tx_records)
        await time_out_assert(15, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node)

        await time_out_assert(15, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(15, wallet_maker.get_unconfirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, wallet_taker.get_confirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            return TradeStatus(trade_rec.status)

        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

        async def assert_trade_tx_number(wallet_node, trade_id, number):
            txs = await wallet_node.wallet_state_manager.tx_store.get_transactions_by_trade_id(trade_id)
            return len(txs) == number

        # Commented out because it's broken for the test specifically (running new code with an old offer)
        # await time_out_assert(15, assert_trade_tx_number, True, wallet_node_maker, trade_make.trade_id, 1)
        await time_out_assert(15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 3)

        # cat_for_chia
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia)
        assert error is None
        assert success is True
        assert trade_make is not None

        trade_take, tx_records = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)
        assert trade_take is not None
        assert tx_records is not None

        MAKER_CAT_BALANCE -= 4
        MAKER_CHIA_BALANCE += 3
        TAKER_CAT_BALANCE += 4
        TAKER_CHIA_BALANCE -= 3

        cat_wallet_taker: CATWallet = await wallet_node_taker.wallet_state_manager.get_wallet_for_asset_id(
            cat_wallet_maker.get_asset_id()
        )

        await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        await full_node.process_transaction_records(records=tx_records)
        await time_out_assert(15, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node)

        await time_out_assert(15, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(15, wallet_maker.get_unconfirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, wallet_taker.get_confirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
        await time_out_assert(15, assert_trade_tx_number, True, wallet_node_maker, trade_make.trade_id, 1)
        await time_out_assert(15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 2)

        # cat_for_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_cat)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        trade_take, tx_records = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)
        await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
        assert trade_take is not None
        assert tx_records is not None

        second_offer = Offer.from_bytes(trade_take.offer)

        MAKER_CAT_BALANCE -= 5
        MAKER_NEW_CAT_BALANCE += 6
        TAKER_CAT_BALANCE += 5
        TAKER_NEW_CAT_BALANCE -= 6

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        await full_node.process_transaction_records(records=tx_records)
        await time_out_assert(15, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node)

        await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

        # chia_for_multiple_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            chia_for_multiple_cat, driver_dict=driver_dict
        )
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        trade_take, tx_records = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)
        await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
        assert trade_take is not None
        assert tx_records is not None

        third_offer = Offer.from_bytes(trade_take.offer)

        MAKER_CHIA_BALANCE -= 7
        MAKER_CAT_BALANCE += 8
        MAKER_NEW_CAT_BALANCE += 9
        TAKER_CHIA_BALANCE += 7
        TAKER_CAT_BALANCE -= 8
        TAKER_NEW_CAT_BALANCE -= 9

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        await full_node.process_transaction_records(records=tx_records)
        await time_out_assert(15, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node)

        await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

        # multiple_cat_for_chia
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(multiple_cat_for_chia)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        trade_take, tx_records = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)
        await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
        assert trade_take is not None
        assert tx_records is not None

        fourth_offer = Offer.from_bytes(trade_take.offer)

        MAKER_CAT_BALANCE -= 11
        MAKER_NEW_CAT_BALANCE -= 12
        MAKER_CHIA_BALANCE += 10
        TAKER_CAT_BALANCE += 11
        TAKER_NEW_CAT_BALANCE += 12
        TAKER_CHIA_BALANCE -= 10

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        await full_node.process_transaction_records(records=tx_records)
        await time_out_assert(15, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node)

        await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

        # chia_and_cat_for_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_and_cat_for_cat)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        trade_take, tx_records = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)
        await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
        assert trade_take is not None
        assert tx_records is not None

        fifth_offer = Offer.from_bytes(trade_take.offer)

        MAKER_CHIA_BALANCE -= 13
        MAKER_CAT_BALANCE -= 14
        MAKER_NEW_CAT_BALANCE += 15
        TAKER_CHIA_BALANCE += 13
        TAKER_CAT_BALANCE += 14
        TAKER_NEW_CAT_BALANCE -= 15

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        await full_node.process_transaction_records(records=tx_records)
        await time_out_assert(15, wallets_are_synced, True, [wallet_node_maker, wallet_node_taker], full_node)

        await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

        # This tests an edge case where aggregated offers the include > 2 of the same kind of CAT
        # (and therefore are solved as a complete ring)
        bundle = Offer.aggregate([first_offer, second_offer, third_offer, fourth_offer, fifth_offer]).to_valid_spend()
        program = simple_solution_generator(bundle)
        result: NPCResult = get_name_puzzle_conditions(program, INFINITE_COST, cost_per_byte=0, mempool_mode=True)
        assert result.error is None

    @pytest.mark.asyncio
    async def test_trade_cancellation(self, wallets_prefarm):
        (
            [wallet_node_maker, maker_funds],
            [wallet_node_taker, taker_funds],
            full_node,
        ) = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

        xch_to_cat_amount = uint64(100)

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, xch_to_cat_amount
            )

            tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()

        await full_node.process_transaction_records(records=tx_records)

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
        maker_funds -= xch_to_cat_amount
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

        cat_for_chia = {
            wallet_maker.id(): 1,
            cat_wallet_maker.id(): -2,
        }

        chia_for_cat = {
            wallet_maker.id(): -3,
            cat_wallet_maker.id(): 4,
        }

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
        trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            return TradeStatus(trade_rec.status)

        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None

        await trade_manager_maker.cancel_pending_offer(trade_make.trade_id)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

        # Due to current mempool rules, trying to force a take out of the mempool with a cancel will not work.
        # Uncomment this when/if it does

        # trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        #     Offer.from_bytes(trade_make.offer),
        # )
        # await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
        # assert trade_take is not None
        # assert tx_records is not None
        # await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CONFIRM, trade_manager_taker, trade_take)
        # await time_out_assert(
        #     15,
        #     full_node.tx_id_in_mempool,
        #     True,
        #     Offer.from_bytes(trade_take.offer).to_valid_spend().name(),
        # )

        fee = uint64(2_000_000_000_000)

        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=fee)
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        await full_node.process_transaction_records(records=txs)

        sum_of_outgoing = uint64(0)
        sum_of_incoming = uint64(0)
        for tx in txs:
            if tx.type == TransactionType.OUTGOING_TX.value:
                sum_of_outgoing = uint64(sum_of_outgoing + tx.amount)
            elif tx.type == TransactionType.INCOMING_TX.value:
                sum_of_incoming = uint64(sum_of_incoming + tx.amount)
        assert (sum_of_outgoing - sum_of_incoming) == 0

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)
        # await time_out_assert(15, get_trade_and_status, TradeStatus.FAILED, trade_manager_taker, trade_take)

        await time_out_assert(15, wallet_maker.get_pending_change_balance, 0)
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds - fee)
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, wallet_taker.get_confirmed_balance, taker_funds)

        peer = wallet_node_taker.get_full_node_peer()
        assert peer is not None
        with pytest.raises(ValueError, match="This offer is no longer valid"):
            await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)

        # Now we're going to create the other way around for test coverage sake
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        assert error is None
        assert success is True
        assert trade_make is not None

        # This take should fail since we have no CATs to fulfill it with
        with pytest.raises(
            ValueError,
            match=f"Do not have a wallet for asset ID: {cat_wallet_maker.get_asset_id()} to fulfill offer",
        ):
            await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)

        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=uint64(0))
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        await full_node.process_transaction_records(records=txs)

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    @pytest.mark.asyncio
    async def test_trade_cancellation_balance_check(self, wallets_prefarm):
        (
            [wallet_node_maker, maker_funds],
            [wallet_node_taker, taker_funds],
            full_node,
        ) = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet

        xch_to_cat_amount = uint64(100)

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, xch_to_cat_amount
            )

            tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()

        await full_node.process_transaction_records(records=tx_records)

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
        maker_funds -= xch_to_cat_amount
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

        chia_for_cat = {
            wallet_maker.id(): -(await wallet_maker.get_spendable_balance()),
            cat_wallet_maker.id(): 4,
        }

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            return TradeStatus(trade_rec.status)

        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
        assert error is None
        assert success is True
        assert trade_make is not None
        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=uint64(0))
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        await full_node.process_transaction_records(records=txs)

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)
