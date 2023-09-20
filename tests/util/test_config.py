from __future__ import annotations

from typing import Any, Dict

import pytest

from chia.server.outbound_message import NodeType
from chia.util.config import get_unresolved_peer_infos


@pytest.mark.asyncio
async def test_get_unresolved_peer_infos_with_multiple_farmer_peers() -> None:
    service_config = {
        "farmer_peers": [
            {
                "host": "127.0.0.1",
                "port": 8447,
            },
            {
                "host": "my.farmer.tld",
                "port": 18447,
            },
        ],
    }

    peer_infos = get_unresolved_peer_infos(service_config, NodeType.FARMER)

    assert len(peer_infos) == 2
    assert peer_infos[0].host == "127.0.0.1"
    assert peer_infos[0].port == 8447
    assert peer_infos[1].host == "my.farmer.tld"
    assert peer_infos[1].port == 18447


@pytest.mark.asyncio
async def test_get_unresolved_peer_infos_with_single_farmer_peer() -> None:
    service_config = {
        "farmer_peer": {
            "host": "my.farmer.tld",
            "port": 18447,
        },
    }

    peer_infos = get_unresolved_peer_infos(service_config, NodeType.FARMER)

    assert len(peer_infos) == 1
    assert peer_infos[0].host == "my.farmer.tld"
    assert peer_infos[0].port == 18447


@pytest.mark.asyncio
async def test_get_unresolved_peer_infos_with_single_farmer_peer_and_multiple_farmer_peers() -> None:
    service_config = {
        "farmer_peer": {
            "host": "my.farmer.tld",
            "port": 18447,
        },
        "farmer_peers": [
            {
                "host": "127.0.0.1",
                "port": 8447,
            },
            {
                "host": "my.other.farmer.tld",
                "port": 18447,
            },
        ],
    }

    peer_infos = get_unresolved_peer_infos(service_config, NodeType.FARMER)

    assert len(peer_infos) == 1
    assert peer_infos[0].host == "my.farmer.tld"
    assert peer_infos[0].port == 18447


@pytest.mark.asyncio
async def test_get_unresolved_peer_infos_with_multiple_full_node_peers() -> None:
    service_config = {
        "full_node_peers": [
            {
                "host": "127.0.0.1",
                "port": 8444,
            },
            {
                "host": "my.full-node.tld",
                "port": 18444,
            },
        ],
    }

    peer_infos = get_unresolved_peer_infos(service_config, NodeType.FULL_NODE)

    assert len(peer_infos) == 2
    assert peer_infos[0].host == "127.0.0.1"
    assert peer_infos[0].port == 8444
    assert peer_infos[1].host == "my.full-node.tld"
    assert peer_infos[1].port == 18444


@pytest.mark.asyncio
async def test_get_unresolved_peer_infos_with_single_full_node_peer() -> None:
    service_config = {
        "full_node_peer": {
            "host": "my.full-node.tld",
            "port": 18444,
        },
    }

    peer_infos = get_unresolved_peer_infos(service_config, NodeType.FULL_NODE)

    assert len(peer_infos) == 1
    assert peer_infos[0].host == "my.full-node.tld"
    assert peer_infos[0].port == 18444


@pytest.mark.asyncio
async def test_get_unresolved_peer_infos_with_single_full_node_peer_and_multiple_full_node_peers() -> None:
    service_config = {
        "full_node_peer": {
            "host": "my.full-node.tld",
            "port": 18444,
        },
        "full_node_peers": [
            {
                "host": "127.0.0.1",
                "port": 8444,
            },
            {
                "host": "my.other.full-node.tld",
                "port": 18444,
            },
        ],
    }

    peer_infos = get_unresolved_peer_infos(service_config, NodeType.FULL_NODE)

    assert len(peer_infos) == 1
    assert peer_infos[0].host == "my.full-node.tld"
    assert peer_infos[0].port == 18444


@pytest.mark.asyncio
async def test_get_unresolved_peer_infos_without_peer_infos_in_config() -> None:
    service_config: Dict[str, Any] = {}

    peer_infos = get_unresolved_peer_infos(service_config, NodeType.FULL_NODE)

    assert len(peer_infos) == 0
