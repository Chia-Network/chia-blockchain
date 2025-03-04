from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.util.streamable import Streamable, streamable
from chia.wallet.util.transaction_type import TransactionType


class FilterMode(IntEnum):
    include = 1
    exclude = 2


@streamable
@dataclass(frozen=True)
class TransactionTypeFilter(Streamable):
    values: list[uint8]
    mode: uint8  # FilterMode

    @classmethod
    def include(cls, values: list[TransactionType]) -> TransactionTypeFilter:
        return cls([uint8(t.value) for t in values], uint8(FilterMode.include))

    @classmethod
    def exclude(cls, values: list[TransactionType]) -> TransactionTypeFilter:
        return cls([uint8(t.value) for t in values], uint8(FilterMode.exclude))


@streamable
@dataclass(frozen=True)
class AmountFilter(Streamable):
    values: list[uint64]
    mode: uint8  # FilterMode

    @classmethod
    def include(cls, values: list[uint64]) -> AmountFilter:
        return cls(values, mode=uint8(FilterMode.include))

    @classmethod
    def exclude(cls, values: list[uint64]) -> AmountFilter:
        return cls(values, mode=uint8(FilterMode.exclude))


@streamable
@dataclass(frozen=True)
class HashFilter(Streamable):
    values: list[bytes32]
    mode: uint8  # FilterMode

    @classmethod
    def include(cls, values: list[bytes32]) -> HashFilter:
        return cls(values, mode=uint8(FilterMode.include))

    @classmethod
    def exclude(cls, values: list[bytes32]) -> HashFilter:
        return cls(values, mode=uint8(FilterMode.exclude))
