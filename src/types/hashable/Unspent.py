from src.types.hashable import Coin, Hash
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32

@streamable
class Unspent(Streamable):
    """
    These are values that correspond to a CoinName that are used
    in keeping track of the unspent database.
    """
    coin: Coin
    confirmed_block_index: uint32
    spent_block_index: uint32
    spent: bool

    @property
    def name(self) -> Hash:
        return self.coin.name()