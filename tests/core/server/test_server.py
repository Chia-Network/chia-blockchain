from __future__ import annotations

import logging
from typing import Tuple
import pytest
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.shared_protocol import Capability, capabilities
from chia.server import ws_connection
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_duplicate_client_connection(
    two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    _, _, server_1, server_2, _ = two_nodes
    assert await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    assert not await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)


@pytest.mark.asyncio
async def test_capabilities_back_comp_before_17(
    monkeypatch, two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    def getverold():
        return "1.6.0b657"
    monkeypatch.setattr(ws_connection, "chia_full_version_str", getverold)
    _, _, server_1, server_2, _ = two_nodes
    assert await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    con = server_2.get_connections()[0]
    assert con.has_capability(Capability.NONE_RESPONSE) is False

@pytest.mark.asyncio
async def test_capabilities_back_comp_fix_17_or_above(
    monkeypatch, two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    def getver17():
        return "1.7.0b657"
    monkeypatch.setattr(ws_connection, "chia_full_version_str", getver17)
    _, _, server_1, server_2, _ = two_nodes
    assert await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    con = server_2.get_connections()[0]
    assert con.has_capability(Capability.NONE_RESPONSE) is True

