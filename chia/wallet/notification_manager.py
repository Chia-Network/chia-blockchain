from __future__ import annotations
import dataclasses
import logging
import time
import traceback

from blspy import G2Element
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from typing_extensions import Literal

from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.db_wrapper import DBWrapper2
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.notification_store import Notification, NotificationStore
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import NotarizedPayment, Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trading.trade_store import TradeStore
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos_for_spend
from chia.wallet.util.notifications import (
    construct_notification,
    solve_notification,
)
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.puzzles.load_clvm import load_clvm


class NotificationManager:
    wallet_state_manager: Any
    log: logging.Logger
    notification_store: NotificationStore

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        db_wrapper: DBWrapper2,
        name: Optional[str] = None,
    ) -> TradeManager:
        self = NotificationManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.notification_store = await NotificationStore.create(db_wrapper)
        return self

    # async def potentially_add_new_notification(self, coin_state: CoinState, peer: WSChiaConnection) -> bool:
    #     if coin_state.coin.puzzle_hash != NOTIFICATION_HASH or coin_state.spent_height is None:
    #         return False
    #     else:
    #         response: List[CoinState] = await self.wallet_state_manager.wallet_node.get_coin_state(
    #             [coin_state.coin.parent_coin_info], peer=peer
    #         )
    #         if len(response) == 0:
    #             self.log.warning(f"Could not find a parent coin with ID: {coin_state.coin.parent_coin_info}")
    #             return None, None
    #         parent_coin_state = response[0]
    #         assert parent_coin_state.spent_height == coin_state.created_height
    #
    #         parent_spend: Optional[CoinSpend] = await self.wallet_state_manager.wallet_node.fetch_puzzle_solution(
    #             parent_coin_state.spent_height, parent_coin_state.coin, peer
    #         )
    #
    #         _, msg = uncurry_notification_launcher(parent_spend.puzzle_reveal.to_program())
    #         await self.notification_store.add_notification(
    #             Notification(
    #                 coin_state.coin.name(),
    #                 bytes(msg.as_python()),
    #                 uint64(coin_state.coin.amount),
    #             )
    #         )
    #         return True

    async def potentially_add_new_notification(self, coin_state: CoinState, parent_spend: CoinSpend) -> bool:
        if (
            coin_state.spent_height is None
            or not self.wallet_state_manager.wallet_node.config.get("accept_notifications", False)
            or self.wallet_state_manager.wallet_node.config.get("required_notification_amount", 0)
            > coin_state.coin.amount
        ):
            return False
        else:
            coin_name: bytes32 = coin_state.coin.name()
            memos: Dict[bytes32, List[bytes]] = compute_memos_for_spend(parent_spend)
            coin_memos: List[bytes] = memos.get(coin_name, [])
            if (
                len(coin_memos) == 2
                and construct_notification(
                    coin_memos[0], Program.to(coin_memos[1]).get_tree_hash(), coin_state.coin.amount
                ).get_tree_hash()
                == coin_state.coin.puzzle_hash
            ):
                await self.notification_store.add_notification(
                    Notification(
                        coin_state.coin.name(),
                        coin_memos[1],
                        uint64(coin_state.coin.amount),
                    )
                )
            return True

    async def send_new_notification(
        self, target: bytes32, msg: bytes, amount: uint64, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        origin_coin: bytes32 = next(iter(await self.wallet_state_manager.main_wallet.select_coins(amount))).name()
        msg_as_prog: Program = Program.to(msg).get_tree_hash()
        notification_puzzle: Program = construct_notification(target, msg_as_prog, amount)
        notification_hash: bytes32 = notification_puzzle.get_tree_hash()
        notification_coin: Coin = Coin(origin_coin, notification_hash, amount)
        notification_spend = CoinSpend(
            notification_coin,
            notification_puzzle,
            solve_notification(),
        )
        extra_spend_bundle = SpendBundle([notification_spend], G2Element())
        chia_tx = await self.wallet_state_manager.main_wallet.generate_signed_transaction(
            amount,
            notification_hash,
            fee,
            origin_id=origin_coin,
            coin_announcements_to_consume={Announcement(notification_coin.name(), b"")},
            memos=[target, msg],
        )
        return dataclasses.replace(
            chia_tx, spend_bundle=SpendBundle.aggregate([chia_tx.spend_bundle, extra_spend_bundle])
        )
