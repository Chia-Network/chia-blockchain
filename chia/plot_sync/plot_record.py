from __future__ import annotations

from dataclasses import dataclass

from chia_rs import G1Element, PlotParam
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.plotting.util import PlotInfo
from chia.protocols.harvester_protocol import Plot, PlotV2


@dataclass(frozen=True)
class PlotRecord:
    filename: str
    plot_param: PlotParam
    plot_id: bytes32
    pool_public_key: G1Element | None
    pool_contract_puzzle_hash: bytes32 | None
    plot_public_key: G1Element
    file_size: uint64
    time_modified: uint64
    compression_level: uint8 | None

    def param(self) -> PlotParam:
        return self.plot_param

    @classmethod
    def from_plot_info(cls, plot_info: PlotInfo) -> PlotRecord:
        prover = plot_info.prover
        return cls(
            filename=prover.get_filename(),
            plot_param=prover.get_param(),
            plot_id=prover.get_id(),
            pool_public_key=plot_info.pool_public_key,
            pool_contract_puzzle_hash=plot_info.pool_contract_puzzle_hash,
            plot_public_key=plot_info.plot_public_key,
            file_size=uint64(plot_info.file_size),
            time_modified=uint64(plot_info.time_modified),
            compression_level=prover.get_compression_level(),
        )

    @classmethod
    def from_plot(cls, plot: Plot) -> PlotRecord:
        return cls(
            filename=plot.filename,
            plot_param=plot.param(),
            plot_id=plot.plot_id,
            pool_public_key=plot.pool_public_key,
            pool_contract_puzzle_hash=plot.pool_contract_puzzle_hash,
            plot_public_key=plot.plot_public_key,
            file_size=plot.file_size,
            time_modified=plot.time_modified,
            compression_level=plot.compression_level,
        )

    @classmethod
    def from_sync_plot(cls, plot: PlotV2) -> PlotRecord:
        if plot.version == 1:
            plot_param = PlotParam.make_v1(plot.size)
        else:
            plot_param = PlotParam.make_v2(plot.plot_index, plot.meta_group, plot.strength)
        return cls(
            filename=plot.filename,
            plot_param=plot_param,
            plot_id=plot.plot_id,
            pool_public_key=plot.pool_public_key,
            pool_contract_puzzle_hash=plot.pool_contract_puzzle_hash,
            plot_public_key=plot.plot_public_key,
            file_size=plot.file_size,
            time_modified=plot.time_modified,
            compression_level=plot.compression_level,
        )

    def to_plot(self) -> Plot:
        if self.plot_param.size_v1 is not None:
            size = uint8(self.plot_param.size_v1)
        else:
            assert self.plot_param.strength_v2 is not None
            size = uint8(0x80 | self.plot_param.strength_v2)
        return Plot(
            filename=self.filename,
            size=size,
            plot_id=self.plot_id,
            pool_public_key=self.pool_public_key,
            pool_contract_puzzle_hash=self.pool_contract_puzzle_hash,
            plot_public_key=self.plot_public_key,
            file_size=self.file_size,
            time_modified=self.time_modified,
            compression_level=self.compression_level,
        )
