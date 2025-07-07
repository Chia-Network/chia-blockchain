from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SolverInfo(Streamable):
    plot_size: uint8
    plot_diffculty: uint64
    quality_string: bytes32
