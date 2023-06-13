from __future__ import annotations

import logging
from typing import cast

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RequestChildren
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.server.outbound_message import make_msg
from chia.simulator.setup_nodes import SimulatorsAndWalletsServices
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16


@pytest.mark.asyncio
async def test_unknown_messages(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    caplog: pytest.LogCaptureFixture,
) -> None:
    [full_node_service], [wallet_service], bt = one_wallet_and_one_simulator_services
    wallet_node = wallet_service._node
    full_node = full_node_service._node
    await wallet_node.server.start_client(
        PeerInfo(self_hostname, uint16(cast(FullNodeAPI, full_node_service._api).server._port)), None
    )
    send_connection = full_node.server.all_connections[wallet_node.server.node_id]
    receive_connection = wallet_node.server.all_connections[full_node.server.node_id]
    receive_connection.api = CrawlerAPI(Crawler(bt.config["seeder"], bt.root_path, bt.constants))
    msg = make_msg(ProtocolMessageTypes.request_children, RequestChildren(bytes32(b"\0" * 32)))

    def receiving_failed() -> bool:
        return "Peer trying to call non api function request_children" in caplog.text

    with caplog.at_level(logging.ERROR):
        assert await send_connection.send_message(msg)
        await time_out_assert(10, receiving_failed)
