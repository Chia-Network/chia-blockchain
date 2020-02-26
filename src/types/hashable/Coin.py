import io
from dataclasses import dataclass
from typing import List

from clvm.casts import int_to_bytes, int_from_bytes

from src.types.sized_bytes import bytes32
from src.util.hash import std_hash
from src.util.ints import uint64
from src.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class Coin(Streamable):
    """
    This structure is used in the body for the reward and fees genesis coins.
    """

    parent_coin_info: bytes32
    puzzle_hash: bytes32
    amount: uint64

    def name(self) -> bytes32:
        return self.get_hash()

    @property
    def name_str(self) -> str:
        return self.name().hex()

    @classmethod
    def from_bytes(cls, blob):
        parent_coin_info = blob[:32]
        puzzle_hash = blob[32:64]
        amount = int_from_bytes(blob[64:])
        return Coin(parent_coin_info, puzzle_hash, uint64(amount))

    def __bytes__(self):
        f = io.BytesIO()
        f.write(self.parent_coin_info)
        f.write(self.puzzle_hash)
        f.write(int_to_bytes(self.amount))
        return f.getvalue()


def hash_coin_list(coin_list: List[Coin]) -> bytes32:
    coin_list.sort(key=lambda x: x.name_str, reverse=True)
    buffer = bytearray()

    for coin in coin_list:
        buffer.extend(coin.name())

    return std_hash(buffer)
