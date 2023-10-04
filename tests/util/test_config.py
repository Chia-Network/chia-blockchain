from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Set

from chia.server.outbound_message import NodeType
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.config import get_unresolved_peer_infos
from chia.util.ints import uint16
from tests.util.misc import DataCase, datacases


@dataclass
class GetUnresolvedPeerInfosCase(DataCase):
    id: str
    service_config: Dict[str, Any]
    requested_node_type: NodeType
    expected_peer_infos: Set[UnresolvedPeerInfo]


@datacases(
    GetUnresolvedPeerInfosCase(
        id="multiple farmer peers",
        service_config={
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
        },
        requested_node_type=NodeType.FARMER,
        expected_peer_infos={
            UnresolvedPeerInfo(host="127.0.0.1", port=uint16(8447)),
            UnresolvedPeerInfo(host="my.farmer.tld", port=uint16(18447)),
        },
    ),
    GetUnresolvedPeerInfosCase(
        id="single farmer peer",
        service_config={
            "farmer_peer": {
                "host": "my.farmer.tld",
                "port": 18447,
            },
        },
        requested_node_type=NodeType.FARMER,
        expected_peer_infos={
            UnresolvedPeerInfo(host="my.farmer.tld", port=uint16(18447)),
        },
    ),
    GetUnresolvedPeerInfosCase(
        id="single farmer peer and multiple farmer peers",
        service_config={
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
        },
        requested_node_type=NodeType.FARMER,
        expected_peer_infos={
            UnresolvedPeerInfo(host="my.farmer.tld", port=uint16(18447)),
            UnresolvedPeerInfo(host="127.0.0.1", port=uint16(8447)),
            UnresolvedPeerInfo(host="my.other.farmer.tld", port=uint16(18447)),
        },
    ),
    GetUnresolvedPeerInfosCase(
        id="multiple full node peers",
        service_config={
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
        },
        requested_node_type=NodeType.FULL_NODE,
        expected_peer_infos={
            UnresolvedPeerInfo(host="127.0.0.1", port=uint16(8444)),
            UnresolvedPeerInfo(host="my.full-node.tld", port=uint16(18444)),
        },
    ),
    GetUnresolvedPeerInfosCase(
        id="single full node peer",
        service_config={
            "full_node_peer": {
                "host": "my.full-node.tld",
                "port": 18444,
            },
        },
        requested_node_type=NodeType.FULL_NODE,
        expected_peer_infos={
            UnresolvedPeerInfo(host="my.full-node.tld", port=uint16(18444)),
        },
    ),
    GetUnresolvedPeerInfosCase(
        id="single full node peer and multiple full node peers",
        service_config={
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
        },
        requested_node_type=NodeType.FULL_NODE,
        expected_peer_infos={
            UnresolvedPeerInfo(host="my.full-node.tld", port=uint16(18444)),
            UnresolvedPeerInfo(host="127.0.0.1", port=uint16(8444)),
            UnresolvedPeerInfo(host="my.other.full-node.tld", port=uint16(18444)),
        },
    ),
    GetUnresolvedPeerInfosCase(
        id="no peer info in config",
        service_config={},
        requested_node_type=NodeType.FULL_NODE,
        expected_peer_infos=set(),
    ),
)
def test_get_unresolved_peer_infos(case: GetUnresolvedPeerInfosCase) -> None:
    assert get_unresolved_peer_infos(case.service_config, case.requested_node_type) == case.expected_peer_infos
