from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from chia._tests.util.time_out_assert import time_out_assert
from chia.harvester.harvester import Harvester
from chia.plot_sync.sender import Sender
from chia.protocols.harvester_protocol import PlotSyncIdentifier
from chia.server.outbound_message import Message, NodeType
from chia.types.aliases import FarmerService, HarvesterService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo, UnresolvedPeerInfo
from chia.util.ints import uint16, uint64
from chia.util.misc import SplitAsyncManager, split_async_manager


@dataclass
class WSChiaConnectionDummy:
    connection_type: NodeType
    peer_node_id: bytes32
    peer_info: PeerInfo = PeerInfo("127.0.0.1", uint16(0))
    last_sent_message: Optional[Message] = None

    async def send_message(self, message: Message) -> None:
        self.last_sent_message = message

    def get_peer_logging(self) -> PeerInfo:
        return self.peer_info


def get_dummy_connection(node_type: NodeType, peer_id: bytes32) -> WSChiaConnectionDummy:
    return WSChiaConnectionDummy(node_type, peer_id)


def plot_sync_identifier(current_sync_id: uint64, message_id: uint64) -> PlotSyncIdentifier:
    return PlotSyncIdentifier(uint64(int(time.time())), current_sync_id, message_id)


@contextlib.asynccontextmanager
async def start_harvester_service(
    harvester_service: HarvesterService, farmer_service: FarmerService
) -> AsyncIterator[SplitAsyncManager[Harvester]]:
    # Set the `last_refresh_time` of the plot manager to avoid initial plot loading
    harvester: Harvester = harvester_service._node
    harvester.plot_manager.last_refresh_time = time.time()
    harvester_service.reconnect_retry_seconds = 1
    async with split_async_manager(manager=harvester_service.manage(), object=harvester) as split_manager:
        await split_manager.enter()
        harvester_service.add_peer(
            UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port())
        )
        harvester.plot_manager.stop_refreshing()

        assert harvester.plot_sync_sender._sync_id == 0
        assert harvester.plot_sync_sender._next_message_id == 0
        assert harvester.plot_sync_sender._last_sync_id == 0
        assert harvester.plot_sync_sender._messages == []

        def wait_for_farmer_connection(plot_sync_sender: Sender) -> bool:
            return plot_sync_sender._connection is not None

        await time_out_assert(10, wait_for_farmer_connection, True, harvester.plot_sync_sender)

        yield split_manager
