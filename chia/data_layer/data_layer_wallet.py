import logging
from typing import Any
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo


class DataLayerWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    standard_wallet: Wallet
    wallet_id: int
    """
    interface to be used by datalayer for interacting with the chain
    """

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.POOLING_WALLET)

    def id(self) -> uint32:
        return self.wallet_info.id

    async def create_table(self, id: bytes32) -> bool:
        return True

    async def delete_table(self, id: bytes32) -> bool:
        return True

    async def get_table_state(self, id: bytes32) -> bytes:
        return b""

    async def uptate_table_state(self, id: bytes32, new_state: bytes32, action: bytes32) -> bool:
        return True
