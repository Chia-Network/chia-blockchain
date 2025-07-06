from __future__ import annotations

from dataclasses import dataclass

from chia_rs import PlotSize
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SolverInfo(Streamable):
    plot_size: PlotSize
    plot_diffculty: uint64
    quality_string: bytes32
