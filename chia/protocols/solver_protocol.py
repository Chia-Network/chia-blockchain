from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_ints import uint64

from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SolverInfo(Streamable):
    plot_difficulty: uint64
    quality_chain: bytes  # 16 * k bits blob, k (plot size) can be derived from this


@streamable
@dataclass(frozen=True)
class SolverResponse(Streamable):
    quality_chain: bytes
    proof: bytes
