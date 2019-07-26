from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64


@streamable
class CoinbaseInfo:
    puzzle_hash: bytes32
    amount: uint64
