import socket
from pathlib import Path
from ipaddress import ip_address, IPv4Network, IPv6Network
from typing import Iterable, List, Tuple, Union, Any, Optional, Dict
from chia.server.outbound_message import NodeType
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config
from chia.util.ints import uint16


def is_in_network(peer_host: str, networks: Iterable[Union[IPv4Network, IPv6Network]]) -> bool:
    try:
        peer_host_ip = ip_address(peer_host)
        return any(peer_host_ip in network for network in networks)
    except ValueError:
        return False


def is_localhost(peer_host: str) -> bool:
    return peer_host == "127.0.0.1" or peer_host == "localhost" or peer_host == "::1" or peer_host == "0:0:0:0:0:0:0:1"


def class_for_type(type: NodeType) -> Any:
    if type is NodeType.FULL_NODE:
        from chia.full_node.full_node_api import FullNodeAPI

        return FullNodeAPI
    elif type is NodeType.WALLET:
        from chia.wallet.wallet_node_api import WalletNodeAPI

        return WalletNodeAPI
    elif type is NodeType.INTRODUCER:
        from chia.introducer.introducer_api import IntroducerAPI

        return IntroducerAPI
    elif type is NodeType.TIMELORD:
        from chia.timelord.timelord_api import TimelordAPI

        return TimelordAPI
    elif type is NodeType.FARMER:
        from chia.farmer.farmer_api import FarmerAPI

        return FarmerAPI
    elif type is NodeType.HARVESTER:
        from chia.harvester.harvester_api import HarvesterAPI

        return HarvesterAPI
    raise ValueError("No class for type")


def get_host_addr(host: Union[PeerInfo, str], prefer_ipv6: Optional[bool]) -> str:
    # If there was no preference passed in (from config), set the system-wise
    # default here.  Not a great place to locate a default value, and we should
    # probabaly do something to write it into the config, but.  For now...
    if prefer_ipv6 is None:
        prefer_ipv6 = False
    # Use PeerInfo.is_valid() to see if it's already an address
    if isinstance(host, PeerInfo):
        hoststr = host.host
        if host.is_valid(True):
            return hoststr
    else:
        hoststr = host
        if PeerInfo(hoststr, uint16(0)).is_valid(True):
            return hoststr
    addrset: List[
        Tuple["socket.AddressFamily", "socket.SocketKind", int, str, Union[Tuple[str, int], Tuple[str, int, int, int]]]
    ] = socket.getaddrinfo(hoststr, None)
    # Addrset is never empty, an exception is thrown or data is returned.
    for t in addrset:
        if prefer_ipv6 and t[0] == socket.AF_INET6:
            return t[4][0]
        if not prefer_ipv6 and t[0] == socket.AF_INET:
            return t[4][0]
    # If neither matched preference, just return the first available
    return addrset[0][4][0]


def is_trusted_inner(peer_host: str, peer_node_id: bytes32, trusted_peers: Dict, testing: bool) -> bool:
    if trusted_peers is None:
        return False
    if not testing and peer_host == "127.0.0.1":
        return True
    if peer_node_id.hex() not in trusted_peers:
        return False

    return True


def select_port(root_path: Path, addresses: List[Any]) -> uint16:
    global_config = load_config(root_path, "config.yaml")
    prefer_ipv6 = global_config.get("prefer_ipv6", False)
    selected_port: uint16
    for address_string, port, *_ in addresses:
        address = ip_address(address_string)
        if address.version == 6 and prefer_ipv6:
            selected_port = port
            break
        elif address.version == 4 and not prefer_ipv6:
            selected_port = port
            break
    else:
        selected_port = addresses[0][1]  # no matches, just use the first one in the list

    return selected_port
