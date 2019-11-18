from dataclasses import dataclass

from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CoinbaseInfo(Streamable):
    height: uint32
    amount: uint64
    puzzle_hash: bytes32
