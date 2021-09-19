import logging
import time
from typing import Any, Optional, Set, Tuple, List, Dict

from blspy import PrivateKey, G2Element, G1Element

from chia.consensus.block_record import BlockRecord
from chia.pools.pool_config import PoolWalletConfig, load_pool_config, update_pool_config
from chia.pools.pool_wallet_info import (
    PoolWalletInfo,
    PoolSingletonState,
    PoolState,
    FARMING_TO_POOL,
    SELF_POOLING,
    LEAVING_POOL,
    create_pool_state,
)
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION


from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo


class DataLayerWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    target_state: Optional[PoolState]
    standard_wallet: Wallet
    wallet_id: int
    singleton_list: List[Coin]
    """
    interface to be used by datalayer for interacting with the chain
    """

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.POOLING_WALLET)

    def id(self):
        return self.wallet_info.id

    async def create_table(self, id: bytes32) -> bool:
        return True

    async def delete_table(self, id: bytes32) -> bool:
        return True

    async def get_table_state(self, id: bytes32) -> bytes:
        return b""

    async def uptate_table_state(self, id: bytes32, new_state: bytes32, action: bytes32) -> bool:
        return True
