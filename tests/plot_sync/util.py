import time
from dataclasses import dataclass
from typing import Optional

from Crypto.Random import get_random_bytes

from chia.harvester.harvester_api import Harvester
from chia.plot_sync.sender import Sender
from chia.protocols.harvester_protocol import PlotSyncIdentifier
from chia.server.start_service import Service
from chia.server.ws_connection import Message, NodeType
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from tests.time_out_assert import time_out_assert


def get_dummy_connection(node_type: NodeType, peer_id=None):
    @dataclass
    class WSChiaConnection:
        connection_type: NodeType = node_type
        peer_node_id: bytes32 = bytes32(get_random_bytes(32)) if peer_id is None else peer_id
        peer_host: str = "localhost"
        peer_port: int = 0
        last_sent_message: Optional[Message] = None

        async def send_message(self, message: Message):
            self.last_sent_message = message

    return WSChiaConnection()


def plot_sync_identifier(current_sync_id: uint64, message_id: uint64):
    return PlotSyncIdentifier(uint64(int(time.time())), current_sync_id, message_id)


async def start_harvester_service(harvester_service: Service) -> Harvester:
    # Set the `last_refresh_time` of the plot manager to avoid initial plot loading
    harvester: Harvester = harvester_service._node
    harvester.plot_manager.last_refresh_time = time.time()
    await harvester_service.start()
    harvester.plot_manager.stop_refreshing()

    assert harvester.plot_sync_sender._sync_id == 0
    assert harvester.plot_sync_sender._next_message_id == 0
    assert harvester.plot_sync_sender._last_sync_id == 0
    assert harvester.plot_sync_sender._messages == []

    def wait_for_farmer_connection(plot_sync_sender: Sender) -> bool:
        return plot_sync_sender._connection is not None

    await time_out_assert(10, wait_for_farmer_connection, True, harvester.plot_sync_sender)

    return harvester
