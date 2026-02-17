

import json
import logging
import re
from typing import TYPE_CHECKING, Any, ClassVar, cast

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint128
from chia.types.blockchain_format.program import Program
from chia.wallet.gaming_wallet.gaming_info import GamingCoinData, GamingInfo
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import WalletProtocol
from chia.wallet.wallet_state_manager import WalletStateManager

# The purpose of the gaming wallet is to allow the WSM to get notifications about the game coins
# this wallet will differ from usual wallets in that is controlled predominantly by the Wallet RPC
# Furthermore the wallet will act mainly as a sentinel for CoinRecords that are related to the gaming wallet
class GamingWallet:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[WalletProtocol[GamingCoinData]] = cast("GamingWallet", None)

    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    gaming_info: GamingInfo
    standard_wallet: Wallet
    wallet_type: ClassVar[WalletType] = WalletType.GAMING
    wallet_info_type: ClassVar[type[GamingInfo]] = GamingInfo


    @staticmethod
    async def create_new_gaming_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        name: str | None = None,
    ):
        """
        Create a brand new Gaming wallet
        This must be called under the wallet state manager lock
        :return: Gaming wallet
        """

        self = GamingWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)

        self.gaming_info = GamingInfo(
            game_coins=[]
        )
        info_as_string = json.dumps(self.gaming_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name=name, wallet_type=WalletType.GAMING.value, data=info_as_string
        )
        self.wallet_id = self.wallet_info.id

        await self.wallet_state_manager.add_new_wallet(self)

        # This just allows us to cycle through puzzle hashes
        self.puzzle_counter = 0

        return self

    def generate_wallet_name(self) -> str:
        """
        Generate a new Gaming wallet name
        :return: wallet name
        """
        max_num = 0
        for wallet in self.wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.GAMING:
                matched = re.search(r"^Profile (\d+)$", wallet.get_name())
                if matched and int(matched.group(1)) > max_num:
                    max_num = int(matched.group(1))
        return f"Gaming Wallet #{max_num + 1}"

    async def register_game_coin(self, coin_id: bytes32) -> None:
        self.gaming_info.game_coins.append(coin_id)
        await self.wallet_state_manager.add_interested_coin_ids([coin_id], [self.wallet_id])
        await self.save_info(self.gaming_info)

    async def save_info(self, gaming_info: GamingInfo):
        self.gaming_info = gaming_info
        current_info = self.wallet_info
        data_str = json.dumps(gaming_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)
    
    # The following functions are expected to exist by WSM, but are just stubs for our uses
    async def get_spendable_balance(self, unspent_records=None) -> uint128:
        return uint128(0)

    # This might not be neccessary
    # def puzzle_for_pk(self, pubkey: G1Element) -> Program:
    #     return Program.to(0)

    # This will populate the coin record store with the stored puzzle hashes.
    # This is a hack. Oh well.
    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        self.puzzle_counter += 1
        return self.gaming_info.game_coins[self.puzzle_counter % len(self.gaming_info.game_coins)].puzzle_hash