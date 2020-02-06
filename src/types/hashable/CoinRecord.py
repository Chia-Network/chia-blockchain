from dataclasses import dataclass

from src.types.hashable.Coin import Coin
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32, uint8


@dataclass(frozen=True)
@streamable
class CoinRecord(Streamable):
    """
    These are values that correspond to a CoinName that are used
    in keeping track of the unspent database.
    """

    coin: Coin
    confirmed_block_index: uint32
    spent_block_index: uint32
    spent: uint8
    coinbase: uint8

    @property
    def name(self) -> bytes32:
        return self.coin.name()
