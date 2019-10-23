from src.util.streamable import streamable, Streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class CoinbaseInfo(Streamable):
    height: uint32
    amount: uint64
    puzzle_hash: bytes32
