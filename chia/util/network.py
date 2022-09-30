from __future__ import annotations

import asyncio
import logging
import socket
import ssl

from aiohttp import web
from aiohttp.log import web_logger
from dataclasses import dataclass
from ipaddress import ip_address, IPv4Network, IPv6Network
from typing import Iterable, List, Tuple, Union, Any, Optional, Dict
from typing_extensions import final
from chia.server.outbound_message import NodeType
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16


@final
@dataclass
class WebServer:
    runner: web.AppRunner
    listen_port: uint16
    _close_task: Optional[asyncio.Task[None]] = None

    @classmethod
    async def create(
        cls,
        hostname: str,
        port: uint16,
        routes: List[web.RouteDef],
        max_request_body_size: int = 1024**2,  # Default `client_max_size` from web.Application
        ssl_context: Optional[ssl.SSLContext] = None,
        keepalive_timeout: int = 75,  # Default from aiohttp.web
        shutdown_timeout: int = 60,  # Default `shutdown_timeout` from web.TCPSite
        prefer_ipv6: bool = False,
        logger: logging.Logger = web_logger,
    ) -> WebServer:
        app = web.Application(client_max_size=max_request_body_size, logger=logger)
        runner = web.AppRunner(app, access_log=None, keepalive_timeout=keepalive_timeout)

        runner.app.add_routes(routes)
        await runner.setup()
        site = web.TCPSite(runner, hostname, int(port), ssl_context=ssl_context, shutdown_timeout=shutdown_timeout)
        await site.start()

        #
        # On a dual-stack system, we want to get the (first) IPv4 port unless
        # prefer_ipv6 is set in which case we use the IPv6 port
        #
        if port == 0:
            port = select_port(prefer_ipv6, runner.addresses)

        return cls(runner=runner, listen_port=uint16(port))

    async def _close(self) -> None:
        await self.runner.shutdown()
        await self.runner.cleanup()

    def close(self) -> None:
        self._close_task = asyncio.create_task(self._close())

    async def await_closed(self) -> None:
        if self._close_task is None:
            raise RuntimeError("WebServer stop not triggered")
        await self._close_task


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
    # probably do something to write it into the config, but.  For now...
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


def select_port(prefer_ipv6: bool, addresses: List[Any]) -> uint16:
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
