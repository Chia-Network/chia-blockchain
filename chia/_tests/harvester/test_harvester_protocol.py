from __future__ import annotations

import pytest
from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint64
from packaging.version import Version

from chia.protocols.harvester_protocol import (
    Plot,
    Plot2,
    Plot3,
    PlotSyncIdentifier,
    PlotSyncPlotList2,
    RespondPlots2,
    supports_new_plot_serialization,
    supports_plot_groups,
)
from chia.protocols.outbound_message import NodeType
from chia.protocols.shared_protocol import protocol_version


def test_old_v2_plot_param_uses_legacy_zero_index_and_meta_group() -> None:
    plot = Plot(
        filename="v2.gplot",
        size=uint8(0x80 | 3),
        plot_id=bytes32.zeros,
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(0),
        time_modified=uint64(0),
        compression_level=uint8(0),
    )

    param = plot.param()

    assert param.size_v1 is None
    assert param.strength_v2 == 3
    assert param.plot_index == 0
    assert param.meta_group == 0


def test_v2_plot3_param_preserves_index_and_meta_group() -> None:
    plot = Plot3(
        filename="v2.gplot",
        size=uint8(0x80 | 3),
        plot_id=bytes32.zeros,
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(0),
        time_modified=uint64(0),
        compression_level=uint8(0),
        plot_index=uint16(1234),
        meta_group=uint8(56),
        group_size=uint16(8),
    )

    param = plot.param()

    assert param.size_v1 is None
    assert param.strength_v2 == 3
    assert param.plot_index == 1234
    assert param.meta_group == 56


def test_new_plot_serialization_starts_at_0_0_38() -> None:
    assert not supports_new_plot_serialization(Version("0.0.37"))
    assert supports_new_plot_serialization(Version("0.0.38"))


def test_plot_group_serialization_starts_at_0_0_39() -> None:
    assert not supports_plot_groups(Version("0.0.38"))
    assert supports_plot_groups(Version("0.0.39"))
    assert protocol_version[NodeType.FARMER] == protocol_version[NodeType.HARVESTER] == "0.0.39"


@pytest.mark.parametrize("size", [32, 0x83], ids=["v1", "v2"])
def test_released_0_0_38_inventory_wire_layout(size: int) -> None:
    # Frozen Plot2 fixture from the 2.7.4 release, with the size byte varied to
    # exercise V1 and V2 inventory. Do not regenerate this compatibility fixture.
    released_plot = bytes.fromhex(
        "00000006706c6f745f317cb2eb7e5c5239e8610a9dd0e137e185966ebb430faf31ae4a0e55d86251065b98"
        "01a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        "011c96d26def7be696f12e7ebb91d50211e6217ce5d9087c9cd1b84782d5d4b237"
        "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        "2ebf02f3d4a4fd7c23b5fb3085e2182201000c4905"
    )
    released_plot = released_plot[:10] + bytes([size]) + released_plot[11:]
    plot = Plot2.from_bytes(released_plot)
    assert bytes(plot) == released_plot
    assert plot.size == size
    assert plot.plot_index == 3145
    assert plot.meta_group == 5

    # Multiple entries and non-empty trailing lists detect shifted layouts.
    inventory = b"\x00\x00\x00\x02" + released_plot * 2 + b"\x00\x00\x00\x01\x00\x00\x00\x03str" * 2
    response = RespondPlots2([plot, plot], ["str"], ["str"])
    assert bytes(response) == inventory
    assert RespondPlots2.from_bytes(inventory) == response

    identifier = PlotSyncIdentifier(uint64(1), uint64(2), uint64(3))
    sync = bytes(identifier) + b"\x00\x00\x00\x02" + released_plot * 2 + b"\x01"
    loaded = PlotSyncPlotList2(identifier, [plot, plot], True)
    assert bytes(loaded) == sync
    assert PlotSyncPlotList2.from_bytes(sync) == loaded


def test_plot_group_serialization_preserves_plot2_layout() -> None:
    plot = Plot3(
        "group.gplot",
        uint8(0x83),
        bytes32.zeros,
        None,
        None,
        G1Element(),
        uint64(100),
        uint64(200),
        uint8(0),
        uint16(1234),
        uint8(56),
        uint16(8),
    )
    legacy = plot.to_plot2()
    expected = (
        b"\x00\x00\x00\x0bgroup.gplot\x83"
        + bytes32.zeros
        + b"\x00\x00"
        + bytes(G1Element())
        + b"\x00\x00\x00\x00\x00\x00\x00\x64"
        + b"\x00\x00\x00\x00\x00\x00\x00\xc8\x01\x00\x04\xd2\x38"
    )
    assert bytes(legacy) == expected
    assert Plot2.from_bytes(expected) == legacy
    assert legacy.param().plot_index == 1234
    assert legacy.param().meta_group == 56
    assert legacy.param().strength_v2 == 3
    assert bytes(plot) == expected + b"\x00\x08"
    assert Plot3.from_bytes(bytes(plot)) == plot
