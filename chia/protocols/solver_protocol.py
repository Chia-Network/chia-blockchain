from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_ints import uint64

from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SolverInfo(Streamable):
    plot_difficulty: uint64
    partial_proof: bytes  # 16 * k bits blob, k (plot size) can be derived from this


@streamable
@dataclass(frozen=True)
class SolverResponse(Streamable):
    partial_proof: bytes
    proof: bytes
