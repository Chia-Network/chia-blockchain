from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional, Set

from blspy import G2Element

from chia.protocols.wallet_protocol import CoinState
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64
from chia.wallet.notification_store import Notification, NotificationStore
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos_for_spend
from chia.wallet.util.notifications import construct_notification
from chia.wallet.util.wallet_types import WalletType


class NotificationManager:
    wallet_state_manager: Any
    log: logging.Logger
    notification_store: NotificationStore

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        db_wrapper: DBWrapper2,
        name: Optional[str] = None,
    ) -> NotificationManager:
        self = NotificationManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.notification_store = await NotificationStore.create(db_wrapper)
        return self

    async def potentially_add_new_notification(self, coin_state: CoinState, parent_spend: CoinSpend) -> bool:
        coin_name: bytes32 = coin_state.coin.name()
        if (
            coin_state.spent_height is None
            or not self.wallet_state_manager.wallet_node.config.get("enable_notifications", True)
            or self.wallet_state_manager.wallet_node.config.get("required_notification_amount", 100000000)
            > coin_state.coin.amount
            or await self.notification_store.notification_exists(coin_name)
        ):
            return False
        else:
            memos: Dict[bytes32, List[bytes]] = compute_memos_for_spend(parent_spend)
            coin_memos: List[bytes] = memos.get(coin_name, [])
            if len(coin_memos) == 0 or len(coin_memos[0]) != 32:
                return False
            wallet_identifier = await self.wallet_state_manager.get_wallet_identifier_for_puzzle_hash(
                bytes32(coin_memos[0])
            )
            if (
                wallet_identifier is not None
                and wallet_identifier.type == WalletType.STANDARD_WALLET
                and len(coin_memos) == 2
                and construct_notification(bytes32(coin_memos[0]), uint64(coin_state.coin.amount)).get_tree_hash()
                == coin_state.coin.puzzle_hash
            ):
                if len(coin_memos[1]) > 10000:  # 10KB
                    return False
                await self.notification_store.add_notification(
                    Notification(
                        coin_state.coin.name(),
                        coin_memos[1],
                        uint64(coin_state.coin.amount),
                        uint32(coin_state.spent_height),
                    )
                )
                self.wallet_state_manager.state_changed("new_on_chain_notification")
            return True

    async def send_new_notification(
        self, target: bytes32, msg: bytes, amount: uint64, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        coins: Set[Coin] = await self.wallet_state_manager.main_wallet.select_coins(uint64(amount + fee))
        origin_coin: bytes32 = next(iter(coins)).name()
        notification_puzzle: Program = construct_notification(target, amount)
        notification_hash: bytes32 = notification_puzzle.get_tree_hash()
        notification_coin: Coin = Coin(origin_coin, notification_hash, amount)
        notification_spend = CoinSpend(
            notification_coin,
            notification_puzzle,
            Program.to(None),
        )
        extra_spend_bundle = SpendBundle([notification_spend], G2Element())
        chia_tx = await self.wallet_state_manager.main_wallet.generate_signed_transaction(
            amount,
            notification_hash,
            fee,
            coins=coins,
            origin_id=origin_coin,
            coin_announcements_to_consume={Announcement(notification_coin.name(), b"")},
            memos=[target, msg],
        )
        full_tx: TransactionRecord = dataclasses.replace(
            chia_tx, spend_bundle=SpendBundle.aggregate([chia_tx.spend_bundle, extra_spend_bundle])
        )
        return full_tx
