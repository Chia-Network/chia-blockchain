from dataclasses import dataclass
from typing import Any, List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.clvm import int_from_bytes, int_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


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
        # This does not use streamable format for serialization. Look at the __bytes__ method that is being overridden:
        # The amount is serialized using CLVM serialization.
        return self.get_hash()

    def as_list(self) -> List[Any]:
        return [self.parent_coin_info, self.puzzle_hash, self.amount]

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
        return self.parent_coin_info + self.puzzle_hash + int_to_bytes(self.amount)


def hash_coin_list(coin_list: List[Coin]) -> bytes32:
    coin_list.sort(key=lambda x: x.name_str, reverse=True)
    buffer = bytearray()

    for coin in coin_list:
        buffer.extend(coin.name())

    return std_hash(buffer)
