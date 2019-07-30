from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32


@streamable
class CoinbaseInfo:
    height: uint32
    amount: uint64
    puzzle_hash: bytes32
