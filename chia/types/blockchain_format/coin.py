from dataclasses import dataclass
from typing import Any, List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.clvm import int_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Coin(Streamable):
    """
    This structure is used in the body for the reward and fees genesis coins.
    """

    parent_coin_info: bytes32  # down with this sort of thing.
    puzzle_hash: bytes32
    amount: uint64

    def get_hash(self) -> bytes32:
        # This does not use streamable format for hashing, the amount is
        # serialized using CLVM integer format.

        # Note that int_to_bytes() will prepend a 0 to integers where the most
        # significant bit is set, to encode it as a positive number. This
        # despite "amount" being unsigned. This way, a CLVM program can generate
        # these hashes easily.
        return std_hash(self.parent_coin_info + self.puzzle_hash + int_to_bytes(self.amount))

    def name(self) -> bytes32:
        return self.get_hash()

    def as_list(self) -> List[Any]:
        return [self.parent_coin_info, self.puzzle_hash, self.amount]

    @property
    def name_str(self) -> str:
        return self.name().hex()

    @classmethod
    def from_bytes(cls, blob):
        # this function is never called. We rely on the standard streamable
        # protocol for both serialization and parsing of Coin.
        # using this function may be ambiguous the same way __bytes__() is.
        assert False

    def __bytes__(self) -> bytes:  # pylint: disable=E0308
        # this function is never called and calling it would be ambiguous. Do
        # you want the format that's hashed or the format that's serialized?
        assert False


def hash_coin_list(coin_list: List[Coin]) -> bytes32:
    coin_list.sort(key=lambda x: x.name_str, reverse=True)
    buffer = bytearray()

    for coin in coin_list:
        buffer.extend(coin.name())

    return std_hash(buffer)
