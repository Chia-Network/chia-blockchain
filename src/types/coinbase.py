from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from dataclasses import dataclass


# @streamable

@dataclass
class CoinbaseInfo:
    height: uint32
    amount: uint64
    puzzle_hash: bytes32


def f(c: CoinbaseInfo) -> CoinbaseInfo:
    return c


a: int = f(124)

b = CoinbaseInfo