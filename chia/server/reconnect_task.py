import asyncio
import traceback

from typing import Optional

from chia.server.server import ChiaServer
from chia.types.peer_info import PeerInfo
from chia.util.network import get_host_addr


def start_reconnect_task(server: ChiaServer, peer_info_arg: PeerInfo, log, auth: bool, prefer_ipv6: Optional[bool]):
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """
    log.info(f" ==== {prefer_ipv6=} {peer_info_arg=} {traceback.format_stack()}")
    # If peer_info_arg is already an address, use it, otherwise resolve it here.
    if peer_info_arg.is_valid():
        peer_info = peer_info_arg
    else:
        peer_info = PeerInfo(get_host_addr(peer_info_arg, prefer_ipv6), peer_info_arg.port)

    async def connection_check(fs):
        x = True
        while True:
            peer_retry = True
            for _, connection in server.all_connections.items():
                if connection.get_peer_info() == peer_info or connection.get_peer_info() == peer_info_arg:
                    peer_retry = False
            if peer_retry:
                if True:#x:
                    log.info(f" ==== {prefer_ipv6} {peer_info_arg=}")
                    log.info(f" ==== {fs}")
                    log.info(f" ==== {traceback.format_stack()}")
                    x = False
                log.info(f"Reconnecting to peer *ahem* {peer_info}")
                try:
                    await server.start_client(peer_info, None, auth=auth)
                except Exception as e:
                    log.info(f"Failed to connect to {peer_info} {e}")
            await asyncio.sleep(3)

    return asyncio.create_task(connection_check(traceback.format_stack()))
