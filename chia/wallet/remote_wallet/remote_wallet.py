from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any, ClassVar, cast

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64, uint128

from chia.types.blockchain_format.coin import Coin
from chia.wallet.remote_wallet.remote_info import RemoteCoinData, RemoteInfo
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import WalletProtocol


# The purpose of the remote wallet is to allow the WSM to get notifications about the remote coins.
# This wallet differs from usual wallets in that it is controlled predominantly by the Wallet RPC.
# Furthermore the wallet will act mainly as a sentinel for CoinRecords that are related to the remote wallet.
class RemoteWallet:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[WalletProtocol[RemoteCoinData]] = cast("RemoteWallet", None)

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    remote_info: RemoteInfo
    standard_wallet: Wallet
    wallet_info_type: ClassVar[type[RemoteInfo]] = RemoteInfo

    @staticmethod
    async def create_new_remote_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        name: str | None = None,
    ) -> RemoteWallet:
        """
        Create a brand new Remote wallet.
        This must be called under the wallet state manager lock.
        """
        self = RemoteWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)

        self.remote_info = RemoteInfo(remote_coin_ids=[])
        info_as_string = json.dumps(self.remote_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name=name, wallet_type=WalletType.REMOTE.value, data=info_as_string
        )

        await self.wallet_state_manager.add_new_wallet(self)
        return self

    @classmethod
    async def create(cls, wallet_state_manager: Any, wallet: Wallet, wallet_info: WalletInfo) -> RemoteWallet:
        """
        Load an existing Remote wallet from the user store.
        """
        self = cls()
        self.wallet_state_manager = wallet_state_manager
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.log = logging.getLogger(__name__)

        try:
            data = json.loads(wallet_info.data) if wallet_info.data else {}
            self.remote_info = RemoteInfo.from_json_dict(data)
        except Exception:
            # Be resilient to older/invalid data while developing.
            self.remote_info = RemoteInfo(remote_coin_ids=[])

        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.REMOTE

    def id(self) -> uint32:
        return self.wallet_info.id

    def get_name(self) -> str:
        return self.wallet_info.name

    def require_derivation_paths(self) -> bool:
        return False

    def generate_wallet_name(self) -> str:
        max_num = 0
        for wallet in self.wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.REMOTE:
                matched = re.search(r"^Remote Wallet #(\d+)$", wallet.get_name())
                if matched and int(matched.group(1)) > max_num:
                    max_num = int(matched.group(1))
        return f"Remote Wallet #{max_num + 1}"

    async def register_remote_coin(self, coin_id: bytes32) -> None:
        if coin_id not in self.remote_info.remote_coin_ids:
            self.remote_info = replace(self.remote_info, remote_coin_ids=[*self.remote_info.remote_coin_ids, coin_id])
        await self.wallet_state_manager.add_interested_coin_ids([coin_id], [self.wallet_info.id])
        await self.save_info(self.remote_info)

    async def save_info(self, remote_info: RemoteInfo) -> None:
        self.remote_info = remote_info
        data_str = json.dumps(remote_info.to_json_dict())
        self.wallet_info = WalletInfo(self.wallet_info.id, self.wallet_info.name, self.wallet_info.type, data_str)
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info)

    # The following functions are expected to exist by WSM, but are just stubs for our uses
    async def get_confirmed_balance(self, record_list: set[WalletCoinRecord] | None = None) -> uint128:
        return uint128(0)

    async def get_unconfirmed_balance(self, unspent_records: set[WalletCoinRecord] | None = None) -> uint128:
        return uint128(0)

    async def get_spendable_balance(self, unspent_records: set[WalletCoinRecord] | None = None) -> uint128:
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, records: set[WalletCoinRecord] | None = None) -> uint128:
        return uint128(0)

    async def coin_added(self, coin: Coin, height: uint32, peer: Any, coin_data: RemoteCoinData | None) -> None:
        # RemoteWallet doesn't claim ownership of coins via puzzle hashes; it's a sentinel.
        return None

    async def select_coins(self, amount: uint64, action_scope: WalletActionScope) -> set[Coin]:
        raise ValueError("RemoteWallet cannot select coins")

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        return False

    async def generate_signed_transaction(
        self,
        amounts: list[uint64],
        puzzle_hashes: list[bytes32],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: set[Coin] | None = None,
        memos: list[list[bytes]] | None = None,
        extra_conditions: tuple[Any, ...] = tuple(),
        **kwargs: Any,
    ) -> None:
        raise ValueError("RemoteWallet cannot generate transactions")

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise RuntimeError("RemoteWallet does not derive puzzle hashes")
