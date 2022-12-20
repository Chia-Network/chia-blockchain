from dataclasses import dataclass
from typing import List

import io

from hsms.atoms import bytes96, uint32, hexbytes

from .coin_spend import CoinSpend


@dataclass(frozen=True)
class SpendBundle:
    """
    This is a list of coins being spent along with their solution programs, and a single
    aggregated signature. This is the object that most closely corresponds to a bitcoin
    transaction (although because of non-interactive signature aggregation, the boundaries
    between transactions are more flexible than in bitcoin).
    """

    coin_spends: List[CoinSpend]
    aggregated_signature: bytes96

    def __add__(self, other: "SpendBundle") -> "SpendBundle":
        return self.__class__(
            self.coin_spends + other.coin_spends,
            self.aggregated_signature + other.aggregated_signature,
        )

    def __bytes__(self) -> hexbytes:
        s = (
            bytes(uint32(len(self.coin_spends)))
            + b"".join(bytes(_) for _ in self.coin_spends)
            + bytes(self.aggregated_signature)
        )
        return hexbytes(s)

    @classmethod
    def from_bytes(cls, blob) -> "SpendBundle":
        f = io.BytesIO(blob)
        count = uint32.parse(f)
        coin_spends = [CoinSpend.parse(f) for _ in range(count)]
        aggregated_signature = bytes96.from_bytes(f.read())
        return cls(coin_spends, aggregated_signature)
