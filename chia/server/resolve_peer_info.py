from __future__ import annotations

import logging
from typing import Any, Optional

from chia.protocols.outbound_message import NodeType
from chia.types.peer_info import UnresolvedPeerInfo

log = logging.getLogger(__name__)

PEER_INFO_MAPPING: dict[NodeType, str] = {
    NodeType.FULL_NODE: "full_node_peer",
    NodeType.FARMER: "farmer_peer",
}


def get_unresolved_peer_infos(service_config: dict[str, Any], peer_type: NodeType) -> set[UnresolvedPeerInfo]:
    peer_info_key = PEER_INFO_MAPPING[peer_type]
    peer_infos: list[dict[str, Any]] = service_config.get(f"{peer_info_key}s", [])
    peer_info: Optional[dict[str, Any]] = service_config.get(peer_info_key)
    if peer_info is not None:
        peer_infos.append(peer_info)

    return {UnresolvedPeerInfo(host=peer["host"], port=peer["port"]) for peer in peer_infos}


def set_peer_info(
    service_config: dict[str, Any],
    peer_type: NodeType,
    peer_host: Optional[str] = None,
    peer_port: Optional[int] = None,
) -> None:
    peer_info_key = PEER_INFO_MAPPING[peer_type]
    if peer_info_key in service_config:
        if peer_host is not None:
            service_config[peer_info_key]["host"] = peer_host
        if peer_port is not None:
            service_config[peer_info_key]["port"] = peer_port
    elif f"{peer_info_key}s" in service_config and len(service_config[f"{peer_info_key}s"]) > 0:
        if peer_host is not None:
            service_config[f"{peer_info_key}s"][0]["host"] = peer_host
        if peer_port is not None:
            service_config[f"{peer_info_key}s"][0]["port"] = peer_port
