from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SolverInfo(Streamable):
    partial_proof: list[uint64]  # 64 proof fragments
    plot_id: bytes32
    strength: uint8
    size: uint8  # k-size


@streamable
@dataclass(frozen=True)
class SolverResponse(Streamable):
    partial_proof: list[uint64]
    proof: bytes
