from __future__ import annotations

import logging
from typing import cast

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RequestChildren
from chia.seeder.crawler import Crawler
from chia.server.outbound_message import make_msg
from chia.server.start_service import Service
from chia.simulator.setup_nodes import SimulatorsAndWalletsServices
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16


@pytest.mark.asyncio
async def test_unknown_messages(
    self_hostname: str,
    one_node: SimulatorsAndWalletsServices,
    crawler_service: Service[Crawler],
    caplog: pytest.LogCaptureFixture,
) -> None:
    [full_node_service], _, _ = one_node
    crawler = crawler_service._node
    full_node = full_node_service._node
    assert await crawler.server.start_client(
        PeerInfo(self_hostname, uint16(cast(FullNodeAPI, full_node_service._api).server._port)), None
    )
    connection = full_node.server.all_connections[crawler.server.node_id]

    def receiving_failed() -> bool:
        return "Non existing function: request_children" in caplog.text

    with caplog.at_level(logging.ERROR):
        msg = make_msg(ProtocolMessageTypes.request_children, RequestChildren(bytes32(b"\0" * 32)))
        assert await connection.send_message(msg)
        await time_out_assert(10, receiving_failed)
