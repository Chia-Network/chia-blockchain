

import json
import logging
import re
from typing import TYPE_CHECKING, Any, ClassVar, cast
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
        Create a brand new DID wallet
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