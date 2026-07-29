from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from chia_rs import G1Element, PlotParam
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint64

from chia.plot_sync.plot_record import PlotRecord
from chia.plotting.prover import ProverProtocol
from chia.plotting.util import PlotInfo
from chia.protocols.harvester_protocol import Plot, PlotV2


@dataclass
class MockProver:
    filename: str
    plot_param: PlotParam
    plot_id: bytes32
    compression_level: uint8 | None = uint8(0)

    def get_filename(self) -> str:
        return self.filename

    def get_param(self) -> PlotParam:
        return self.plot_param

    def get_id(self) -> bytes32:
        return self.plot_id

    def get_compression_level(self) -> uint8 | None:
        return self.compression_level


def make_plot_info(plot_param: PlotParam, filename: str = "plot.dat") -> PlotInfo:
    return PlotInfo(
        prover=cast(ProverProtocol, MockProver(filename, plot_param, bytes32.zeros, uint8(0))),
        pool_public_key=None,
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=123,
        time_modified=456.0,
    )


def test_from_plot_info_v1() -> None:
    plot_param = PlotParam.make_v1(uint8(32))
    record = PlotRecord.from_plot_info(make_plot_info(plot_param))
    assert record.plot_param == plot_param
    assert record.filename == "plot.dat"
    assert record.file_size == uint64(123)
    assert record.time_modified == uint64(456)


def test_from_plot_info_v2() -> None:
    plot_param = PlotParam.make_v2(uint16(3), uint8(2), uint8(5))
    record = PlotRecord.from_plot_info(make_plot_info(plot_param))
    assert record.plot_param == plot_param
    assert record.plot_param.plot_index == 3
    assert record.plot_param.meta_group == 2
    assert record.plot_param.strength_v2 == 5


def test_from_plot_roundtrip_v1() -> None:
    plot = Plot(
        "plot_v1",
        uint8(32),
        bytes32.zeros,
        None,
        None,
        G1Element(),
        uint64(100),
        uint64(200),
        uint8(1),
    )
    record = PlotRecord.from_plot(plot)
    roundtrip = record.to_plot()
    assert roundtrip.filename == plot.filename
    assert roundtrip.size == plot.size
    assert roundtrip.plot_id == plot.plot_id
    assert roundtrip.file_size == plot.file_size


def test_from_plot_roundtrip_v2_msb() -> None:
    plot = Plot(
        "plot_v2",
        uint8(0x80 | 5),
        bytes32.zeros,
        None,
        None,
        G1Element(),
        uint64(100),
        uint64(200),
        uint8(0),
    )
    record = PlotRecord.from_plot(plot)
    assert record.plot_param.strength_v2 == 5
    roundtrip = record.to_plot()
    assert roundtrip.size == uint8(0x80 | 5)


@pytest.mark.parametrize(
    ["plot_v2", "expected_strength", "expected_plot_index", "expected_meta_group"],
    [
        pytest.param(
            PlotV2(
                "v1_plot",
                uint8(1),
                uint8(32),
                uint8(0),
                uint16(0),
                uint8(0),
                bytes32.zeros,
                None,
                None,
                G1Element(),
                uint64(1),
                uint64(2),
                uint8(0),
            ),
            None,
            0,
            0,
            id="v1",
        ),
        pytest.param(
            PlotV2(
                "v2_plot",
                uint8(2),
                uint8(0),
                uint8(7),
                uint16(4),
                uint8(1),
                bytes32.zeros,
                None,
                None,
                G1Element(),
                uint64(1),
                uint64(2),
                uint8(0),
            ),
            7,
            4,
            1,
            id="v2",
        ),
    ],
)
def test_from_sync_plot(
    plot_v2: PlotV2,
    expected_strength: int | None,
    expected_plot_index: int,
    expected_meta_group: int,
) -> None:
    record = PlotRecord.from_sync_plot(plot_v2)
    assert record.filename == plot_v2.filename
    if expected_strength is None:
        assert record.plot_param.size_v1 == plot_v2.size
    else:
        assert record.plot_param.strength_v2 == expected_strength
        assert record.plot_param.plot_index == expected_plot_index
        assert record.plot_param.meta_group == expected_meta_group
