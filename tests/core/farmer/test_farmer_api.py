from __future__ import annotations

from asyncio import gather, sleep

import pytest

from chia.farmer.farmer_api import FarmerAPI
from chia.protocols import farmer_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64
from tests.conftest import FarmerOneHarvester
from tests.connection_utils import add_dummy_connection


@pytest.mark.asyncio
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
