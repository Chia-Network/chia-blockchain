from __future__ import annotations

import random
from dataclasses import dataclass
from typing import cast

import pytest
from chia_rs import G1Element, PlotParam
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64

from chia._tests.plot_sync.util import get_dummy_connection
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.plot_sync.delta import Delta
from chia.plot_sync.plot_record import PlotRecord
from chia.plot_sync.receiver import Receiver
from chia.plot_sync.sender import Sender, _convert_sync_plot_list, _uses_plot_v2_metadata
from chia.plot_sync.util import State
from chia.plotting.prover import ProverProtocol
from chia.plotting.util import HarvestingMode, PlotInfo
from chia.protocols.harvester_protocol import PlotSyncIdentifier, PlotSyncPlotListV2, PlotSyncStart, PlotV2
from chia.protocols.outbound_message import NodeType
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.simulator.block_tools import BlockTools


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


def make_plot_info(plot_param: PlotParam, filename: str) -> PlotInfo:
    return PlotInfo(
        prover=cast(ProverProtocol, MockProver(filename, plot_param, bytes32.zeros, uint8(0))),
        pool_public_key=None,
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=100,
        time_modified=0.0,
    )


async def dummy_callback(_: bytes32, __: Delta | None) -> None:
    pass


def test_uses_plot_v2_metadata_without_capability(seeded_random: random.Random) -> None:
    connection = get_dummy_connection(NodeType.FARMER, bytes32.random(seeded_random))
    assert not _uses_plot_v2_metadata(connection)  # type: ignore[arg-type]
    assert not _uses_plot_v2_metadata(None)


def test_uses_plot_v2_metadata_with_capability(seeded_random: random.Random) -> None:
    connection = get_dummy_connection(NodeType.FARMER, bytes32.random(seeded_random), [Capability.PLOT_V2_METADATA])
    assert _uses_plot_v2_metadata(connection)  # type: ignore[arg-type]


def test_convert_sync_plot_list_v1_and_v2() -> None:
    v1 = make_plot_info(PlotParam.make_v1(uint8(32)), "v1.plot")
    v2 = make_plot_info(PlotParam.make_v2(uint16(2), uint8(1), uint8(6)), "v2.plot")
    converted = _convert_sync_plot_list([v1, v2])
    assert len(converted) == 2
    assert converted[0].version == uint8(1)
    assert converted[0].size == uint8(32)
    assert converted[1].version == uint8(2)
    assert converted[1].strength == uint8(6)
    assert converted[1].plot_index == uint16(2)
    assert converted[1].meta_group == uint8(1)


def test_process_batch_message_type(bt: BlockTools, seeded_random: random.Random) -> None:
    sender = Sender(bt.plot_manager, HarvestingMode.CPU)
    sender._sync_id = uint64(1)
    sender._next_message_id = uint64(0)

    plot_infos = [make_plot_info(PlotParam.make_v1(uint8(32)), "plot.dat")]

    legacy_connection = get_dummy_connection(NodeType.FARMER, bytes32.random(seeded_random))
    sender.set_connection(legacy_connection)  # type: ignore[arg-type]
    sender.process_batch(plot_infos, 0)
    assert len(sender._messages) == 1
    assert sender._messages[0].message_type == ProtocolMessageTypes.plot_sync_loaded

    sender._messages.clear()
    v2_connection = get_dummy_connection(NodeType.FARMER, bytes32.random(seeded_random), [Capability.PLOT_V2_METADATA])
    sender.set_connection(v2_connection)  # type: ignore[arg-type]
    sender.process_batch(plot_infos, 0)
    assert len(sender._messages) == 1
    v2_message = sender._messages[0]
    assert v2_message.message_type == ProtocolMessageTypes.plot_sync_loaded_v2


@pytest.mark.anyio
async def test_receiver_process_loaded_v2(seeded_random: random.Random) -> None:
    receiver = Receiver(
        get_dummy_connection(NodeType.HARVESTER, bytes32.random(seeded_random)),  # type: ignore[arg-type]
        dummy_callback,  # type: ignore[arg-type]
        DEFAULT_CONSTANTS,
    )
    await receiver.sync_started(
        PlotSyncStart(
            PlotSyncIdentifier(uint64(0), uint64(1), uint64(0)),
            False,
            uint64(0),
            uint32(1),
            uint8(HarvestingMode.CPU),
        )
    )

    plot_v2 = PlotV2(
        "new_plot",
        uint8(2),
        uint8(0),
        uint8(5),
        uint16(3),
        uint8(2),
        bytes32.zeros,
        None,
        None,
        G1Element(),
        uint64(100),
        uint64(200),
        uint8(0),
    )
    await receiver.process_loaded_v2(
        PlotSyncPlotListV2(
            PlotSyncIdentifier(uint64(0), uint64(1), uint64(1)),
            [plot_v2],
            True,
        )
    )

    record = receiver._current_sync.delta.valid.additions["new_plot"]
    assert isinstance(record, PlotRecord)
    assert record.plot_param.strength_v2 == 5
    assert record.plot_param.plot_index == 3
    assert record.plot_param.meta_group == 2
    assert receiver.current_sync().state == State.removed
