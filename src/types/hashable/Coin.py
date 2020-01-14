from dataclasses import dataclass

from src.atoms import hash_pointer
from src.types.hashable.Program import ProgramHash
from src.types.hashable.Hash import std_hash
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Coin(Streamable):
    """
    This structure is used in the body for the reward and fees genesis coins.
    """
    parent_coin_info: bytes
    puzzle_hash: ProgramHash
    amount: uint64

    def name(self) -> "CoinName":
        return CoinName(self)


CoinName: bytes = hash_pointer(Coin, std_hash)

Coin.__annotations__["parent_coin_info"] = CoinName
