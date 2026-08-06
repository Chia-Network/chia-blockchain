from __future__ import annotations

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint64
from packaging.version import Version

from chia.protocols.harvester_protocol import Plot, Plot2, supports_new_plot_serialization


def test_old_v2_plot_param_uses_legacy_zero_index_and_meta_group() -> None:
    plot = Plot(
        filename="v2.plot2",
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


def test_v2_plot2_param_preserves_index_and_meta_group() -> None:
    plot = Plot2(
        filename="v2.plot2",
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
    )

    param = plot.param()

    assert param.size_v1 is None
    assert param.strength_v2 == 3
    assert param.plot_index == 1234
    assert param.meta_group == 56


def test_new_plot_serialization_starts_at_0_0_38() -> None:
    assert not supports_new_plot_serialization(Version("0.0.37"))
    assert supports_new_plot_serialization(Version("0.0.38"))
