from __future__ import annotations

from asyncio import Task, gather, sleep
from collections.abc import Coroutine
from functools import partial
from typing import Any, TypeVar, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from chia_rs.sized_ints import uint8, uint16, uint32, uint64
from packaging.version import Version

from chia._tests.conftest import FarmerOneHarvester
from chia._tests.connection_utils import add_dummy_connection, add_dummy_connection_wsc
from chia._tests.util.network_protocol_data import (
    new_signage_point,
    request_signed_values,
    respond_signatures,
    signed_values,
)
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.outbound_message import Message, NodeType
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.util.hash import std_hash
from chia.util.task_referencer import create_referenced_task

T = TypeVar("T")


async def begin_task(coro: Coroutine[Any, Any, T]) -> Task[T]:
    """Awaitable function that adds a coroutine to the event loop and sets it running."""
    task = create_referenced_task(coro)
    await sleep(0)

    return task


@pytest.mark.anyio
async def test_farmer_ignores_concurrent_duplicate_signage_points(
    farmer_one_harvester: FarmerOneHarvester, self_hostname: str
) -> None:
    _, farmer_service, _ = farmer_one_harvester
    farmer_api: FarmerAPI = farmer_service._api
    farmer_server = farmer_service._server
    incoming_queue, _ = await add_dummy_connection(
        farmer_server, self_hostname, 12312, NodeType.HARVESTER, wait_for_peer_added=False
    )
    # Consume the handshake
    response = (await incoming_queue.get()).type
    assert ProtocolMessageTypes(response).name == "harvester_handshake"

    sp = farmer_protocol.NewSignagePoint(
        std_hash(b"1"), std_hash(b"2"), std_hash(b"3"), uint64(1), uint64(1000000), uint8(2), uint32(1), uint32(0)
    )
    await gather(
        farmer_api.new_signage_point(sp),
        farmer_api.new_signage_point(sp),
        farmer_api.new_signage_point(sp),
    )
    # Wait a bit for the queue to fill
    await sleep(1)

    assert incoming_queue.qsize() == 1
    response = (await incoming_queue.get()).type
    assert ProtocolMessageTypes(response).name == "new_signage_point_harvester"


@pytest.mark.anyio
async def test_farmer_does_not_send_v2_signage_point_to_037_harvester(
    farmer_one_harvester: FarmerOneHarvester, self_hostname: str
) -> None:
    _, farmer_service, _ = farmer_one_harvester
    farmer_api: FarmerAPI = farmer_service._api
    farmer_server = farmer_service._server
    incoming_queue, peer_id = await add_dummy_connection(
        farmer_server, self_hostname, 12312, NodeType.HARVESTER, wait_for_peer_added=False
    )
    await time_out_assert(5, lambda: peer_id in farmer_server.all_connections)
    # Consume the handshake
    response_type = (await incoming_queue.get()).type
    assert ProtocolMessageTypes(response_type).name == "harvester_handshake"

    farmer_server.all_connections[peer_id].protocol_version = Version("0.0.37")
    sp = farmer_protocol.NewSignagePoint(
        std_hash(b"1"),
        std_hash(b"2"),
        std_hash(b"3"),
        uint64(1),
        uint64(1000000),
        uint8(2),
        uint32(1),
        uint32(0),
        filter_challenge=std_hash(b"filter"),
    )

    await farmer_api.new_signage_point(sp)
    await sleep(1)

    assert incoming_queue.qsize() == 0


@pytest.mark.anyio
async def test_farmer_sends_filter_challenge_to_038_harvester(
    farmer_one_harvester: FarmerOneHarvester, self_hostname: str
) -> None:
    _, farmer_service, _ = farmer_one_harvester
    farmer_api: FarmerAPI = farmer_service._api
    farmer_server = farmer_service._server
    incoming_queue, peer_id = await add_dummy_connection(
        farmer_server, self_hostname, 12312, NodeType.HARVESTER, wait_for_peer_added=False
    )
    await time_out_assert(5, lambda: peer_id in farmer_server.all_connections)
    # Consume the handshake
    response_type = (await incoming_queue.get()).type
    assert ProtocolMessageTypes(response_type).name == "harvester_handshake"

    farmer_server.all_connections[peer_id].protocol_version = Version("0.0.38")
    filter_challenge = std_hash(b"filter")
    sp = farmer_protocol.NewSignagePoint(
        std_hash(b"1"),
        std_hash(b"2"),
        std_hash(b"3"),
        uint64(1),
        uint64(1000000),
        uint8(2),
        uint32(1),
        uint32(0),
        filter_challenge=filter_challenge,
    )

    await farmer_api.new_signage_point(sp)
    await sleep(1)

    response = await incoming_queue.get()
    assert ProtocolMessageTypes(response.type) == ProtocolMessageTypes.new_signage_point_harvester
    parsed = harvester_protocol.NewSignagePointHarvester2.from_bytes(response.data)
    assert parsed.filter_challenge == filter_challenge
    assert parsed.peak_height == sp.peak_height
    assert parsed.last_tx_height == sp.last_tx_height


@pytest.mark.anyio
async def test_farmer_responds_with_signed_values(farmer_one_harvester: FarmerOneHarvester, self_hostname: str) -> None:
    _, farmer_service, _ = farmer_one_harvester
    farmer_api: FarmerAPI = farmer_service._api
    farmer_server = farmer_service._server
    dummy_wsc, peer_id = await add_dummy_connection_wsc(
        farmer_server, self_hostname, 12312, NodeType.HARVESTER, wait_for_peer_added=False
    )
    incoming_queue = dummy_wsc.incoming_queue
    # Consume the handshake
    response = (await incoming_queue.get()).type
    assert ProtocolMessageTypes(response).name == "harvester_handshake"
    # Mark our dummy harvester as the harvester which found a proof
    farmer_service._node.quality_str_to_identifiers[request_signed_values.quality_string] = (
        "plot_1",
        new_signage_point.challenge_hash,
        new_signage_point.challenge_chain_sp,
        peer_id,
    )
    setattr(farmer_api, "_process_respond_signatures", lambda res: signed_values)

    signed_values_task: Task[Message | None] = await begin_task(farmer_api.request_signed_values(request_signed_values))

    # Wait a bit for the dummy harvester to receive the signature request and respond with a dummy signature
    await sleep(1)
    assert incoming_queue.qsize() == 1
    request_signatures_message = await incoming_queue.get()
    assert ProtocolMessageTypes(request_signatures_message.type).name == "request_signatures"
    await dummy_wsc.outgoing_queue.put(
        (
            0,
            0,
            Message(
                uint8(ProtocolMessageTypes.respond_signatures.value),
                request_signatures_message.id,
                bytes(respond_signatures),
            ),
            None,
        )
    )

    signed_values_message = await signed_values_task
    assert signed_values_message is not None
    assert ProtocolMessageTypes(signed_values_message.type).name == "signed_values"
    assert signed_values_message.data == bytes(signed_values)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "slot_seconds, sps_per_slot, extra_intervals, expected_lifetime",
    [(600, 64, 3, 18.75), (64, 32, 4, 6.0)],
)
async def test_signage_point_send_deadline(
    slot_seconds: int, sps_per_slot: int, extra_intervals: int, expected_lifetime: float
) -> None:
    farmer = Mock(spec=Farmer)
    farmer.constants = DEFAULT_CONSTANTS.replace(
        SUB_SLOT_TIME_TARGET=uint16(slot_seconds),
        NUM_SPS_SUB_SLOT=uint8(sps_per_slot),
        NUM_SP_INTERVALS_EXTRA=uint8(extra_intervals),
    )
    farmer.sps = {}
    farmer.pool_state = {}
    farmer.cache_add_time = {}
    harvesters = [
        Mock(
            spec=WSChiaConnection,
            connection_type=NodeType.HARVESTER,
            protocol_version=Version(version),
            peer_node_id=std_hash(version.encode()),
            send_message=AsyncMock(),
        )
        for version in ["0.0.36", "0.0.38"]
    ]
    farmer.server = Mock(spec=ChiaServer)
    farmer.server.all_connections = {peer.peer_node_id: peer for peer in harvesters}
    farmer.server.validate_broadcast_message_type = AsyncMock()
    farmer.server.send_to_all_if = partial(ChiaServer.send_to_all_if, farmer.server)
    with patch("chia.farmer.farmer_api.time") as clock:
        clock.monotonic.return_value = 100.0
        clock.time.return_value = 1000.0
        await FarmerAPI(cast(Farmer, farmer)).new_signage_point(new_signage_point)
    # Follow the real broadcast helper to both supported harvester versions.
    for peer in harvesters:
        peer.send_message.assert_awaited_once()
        assert peer.send_message.await_args.kwargs["expires_at"] == pytest.approx(100.0 + expected_lifetime)
