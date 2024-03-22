from __future__ import annotations

from asyncio import Task, create_task, gather, sleep
from typing import Any, Coroutine, Optional, TypeVar

import pytest

from chia._tests.conftest import FarmerOneHarvester
from chia._tests.connection_utils import add_dummy_connection, add_dummy_connection_wsc
from chia._tests.util.network_protocol_data import (
    new_signage_point,
    request_signed_values,
    respond_signatures,
    signed_values,
)
from chia.farmer.farmer_api import FarmerAPI
from chia.protocols import farmer_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message, NodeType
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64

T = TypeVar("T")


async def begin_task(coro: Coroutine[Any, Any, T]) -> Task[T]:
    """Awaitable function that adds a coroutine to the event loop and sets it running."""
    task = create_task(coro)
    await sleep(0)

    return task


@pytest.mark.anyio
async def test_farmer_ignores_concurrent_duplicate_signage_points(
    farmer_one_harvester: FarmerOneHarvester, self_hostname: str
) -> None:
    _, farmer_service, _ = farmer_one_harvester
    farmer_api: FarmerAPI = farmer_service._api
    farmer_server = farmer_service._server
    incoming_queue, peer_id = await add_dummy_connection(farmer_server, self_hostname, 12312, NodeType.HARVESTER)
    # Consume the handshake
    response = (await incoming_queue.get()).type
    assert ProtocolMessageTypes(response).name == "harvester_handshake"

    sp = farmer_protocol.NewSignagePoint(
        std_hash(b"1"), std_hash(b"2"), std_hash(b"3"), uint64(1), uint64(1000000), uint8(2), uint32(1)
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
async def test_farmer_responds_with_signed_values(farmer_one_harvester: FarmerOneHarvester, self_hostname: str) -> None:
    _, farmer_service, _ = farmer_one_harvester
    farmer_api: FarmerAPI = farmer_service._api
    farmer_server = farmer_service._server
    dummy_wsc, peer_id = await add_dummy_connection_wsc(farmer_server, self_hostname, 12312, NodeType.HARVESTER)
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

    signed_values_task: Task[Optional[Message]] = await begin_task(
        farmer_api.request_signed_values(request_signed_values)
    )

    # Wait a bit for the dummy harvester to receive the signature request and respond with a dummy signature
    await sleep(1)
    assert incoming_queue.qsize() == 1
    request_signatures_message = await incoming_queue.get()
    assert ProtocolMessageTypes(request_signatures_message.type).name == "request_signatures"
    await dummy_wsc.outgoing_queue.put(
        Message(
            uint8(ProtocolMessageTypes.respond_signatures.value),
            request_signatures_message.id,
            bytes(respond_signatures),
        )
    )

    signed_values_message = await signed_values_task
    assert signed_values_message is not None
    assert ProtocolMessageTypes(signed_values_message.type).name == "signed_values"
    assert signed_values_message.data == bytes(signed_values)
