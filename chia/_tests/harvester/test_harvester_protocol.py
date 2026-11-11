from __future__ import annotations

import pytest
from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint64
from packaging.version import Version

from chia.protocols.harvester_protocol import (
    Plot,
    Plot3,
    supports_plot_groups,
)
from chia.protocols.outbound_message import NodeType
from chia.protocols.shared_protocol import protocol_version


@pytest.mark.parametrize("compression_level", [None, uint8(0), uint8(5)])
def test_legacy_plot_param_is_v1(compression_level: uint8 | None) -> None:
    plot = Plot(
        filename="v1.plot",
        size=uint8(32),
        plot_id=bytes32.zeros,
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(0),
        time_modified=uint64(0),
        compression_level=compression_level,
    )

    param = plot.param()

    assert param.size_v1 == 32
    assert param.strength_v2 is None
    plot3 = Plot.from_bytes(bytes(plot)).to_plot3()
    assert plot3.compression_level == (compression_level if compression_level is not None else uint8(0))
    assert plot3.param().size_v1 == 32
    assert Plot3.from_bytes(bytes(plot3)) == plot3


def test_v2_plot3_param_uses_group_metadata_without_plot_index() -> None:
    group_plot_id = bytes32.random()
    plot = Plot3(
        filename="v2.gplot",
        size=None,
        plot_id=None,
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(0),
        time_modified=uint64(0),
        compression_level=None,
        meta_group=uint8(56),
        group_plot_id=group_plot_id,
        strength=uint8(3),
        group_size=uint16(8),
    )

    param = plot.param()

    assert param.size_v1 is None
    assert param.strength_v2 == 3
    assert param.plot_index == 0
    assert param.meta_group == 56
    assert plot.group_plot_id == group_plot_id
    assert plot.size is None
    assert plot.plot_id is None
    assert plot.compression_level is None


def test_v1_plot3_keeps_size_plot_id_and_compression_fields() -> None:
    plot_id = bytes32.random()
    plot = Plot3(
        filename="v1.plot",
        size=uint8(32),
        plot_id=plot_id,
        pool_public_key=None,
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(100),
        time_modified=uint64(200),
        compression_level=uint8(5),
        group_plot_id=None,
        strength=None,
        meta_group=None,
        group_size=None,
    )

    assert plot.param().size_v1 == 32
    assert Plot3.from_bytes(bytes(plot)) == plot


def test_plot3_serialization_starts_at_0_0_39() -> None:
    assert not supports_plot_groups(Version("0.0.37"))
    assert supports_plot_groups(Version("0.0.39"))
    assert protocol_version[NodeType.FARMER] == protocol_version[NodeType.HARVESTER] == "0.0.39"


def test_plot_group_serialization_round_trips() -> None:
    group_plot_id = bytes32.zeros
    plot = Plot3(
        filename="group.gplot",
        size=None,
        plot_id=None,
        pool_public_key=None,
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(100),
        time_modified=uint64(200),
        compression_level=None,
        meta_group=uint8(56),
        group_plot_id=group_plot_id,
        strength=uint8(3),
        group_size=uint16(8),
    )
    serialized = bytes(plot)
    assert Plot3.from_bytes(serialized) == plot
