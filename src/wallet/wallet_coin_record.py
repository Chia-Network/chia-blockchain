from dataclasses import dataclass

from src.types.coin import Coin
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32
from src.wallet.util.wallet_types import WalletType


@dataclass(frozen=True)
@streamable
class WalletCoinRecord(Streamable):
    """
    These are values that correspond to a CoinName that are used
    in keeping track of the unspent database.
    """

    coin: Coin
    confirmed_block_index: uint32
    spent_block_index: uint32
    spent: bool
    coinbase: bool
    wallet_type: WalletType
    wallet_id: int

    def name(self) -> bytes32:
        return self.coin.name()
