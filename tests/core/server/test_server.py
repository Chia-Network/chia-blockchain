from __future__ import annotations

from typing import Tuple

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16


@pytest.mark.asyncio
async def test_duplicate_client_connection(
    two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    _, _, server_1, server_2, _ = two_nodes
    assert await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    assert not await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
