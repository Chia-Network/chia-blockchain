import socket
from ipaddress import ip_address, IPv4Network, IPv6Network
from typing import Iterable, List, Tuple, Union, Any, Optional
from chinilla.server.outbound_message import NodeType
from chinilla.types.peer_info import PeerInfo
from chinilla.util.ints import uint16


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
        from chinilla.full_node.full_node_api import FullNodeAPI

        return FullNodeAPI
    elif type is NodeType.WALLET:
        from chinilla.wallet.wallet_node_api import WalletNodeAPI

        return WalletNodeAPI
    elif type is NodeType.INTRODUCER:
        from chinilla.introducer.introducer_api import IntroducerAPI

        return IntroducerAPI
    elif type is NodeType.TIMELORD:
        from chinilla.timelord.timelord_api import TimelordAPI

        return TimelordAPI
    elif type is NodeType.FARMER:
        from chinilla.farmer.farmer_api import FarmerAPI

        return FarmerAPI
    elif type is NodeType.HARVESTER:
        from chinilla.harvester.harvester_api import HarvesterAPI

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
