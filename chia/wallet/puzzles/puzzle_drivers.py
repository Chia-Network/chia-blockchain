from __future__ import annotations

from typing import Protocol, TypeVar

from chia_rs import Coin
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program


class InnerPuzzle(Protocol):
    @property
    def puzzle(self) -> Program: ...

    @property
    def puzzle_hash(self) -> bytes32: ...


_T_InnerPuzzle_co = TypeVar("_T_InnerPuzzle_co", bound=InnerPuzzle, covariant=True)


class OuterPuzzle(InnerPuzzle, Protocol[_T_InnerPuzzle_co]):
    @property
    def inner_puzzle(self) -> _T_InnerPuzzle_co: ...


class SmartCoin(InnerPuzzle, Protocol):
    @property
    def coin(self) -> Coin: ...
