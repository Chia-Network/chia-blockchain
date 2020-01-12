from ...atoms import hash_pointer

from src.util.ints import uint64
from .Hash import std_hash
from .Program import ProgramHash
from src.util.streamable import Streamable, streamable

@streamable
class Coin(Streamable):
    """
    This structure is used in the body for the reward and fees genesis coins.
    """
    parent_coin_info: "CoinName"
    puzzle_hash: ProgramHash
    amount: uint64

    def name(self) -> "CoinName":
        return CoinName(self)


CoinName = hash_pointer(Coin, std_hash)

Coin.__annotations__["parent_coin_info"] = CoinName
