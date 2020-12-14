import asyncio
import socket

from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo


def start_reconnect_task(server: ChiaServer, peer_info_arg: PeerInfo, log, auth: bool):
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """
    peer_info = PeerInfo(socket.gethostbyname(peer_info_arg.host), peer_info_arg.port)

    async def connection_check():
        while True:
            peer_retry = True
            for _, connection in server.all_connections.items():
                if connection.get_peer_info() == peer_info or connection.get_peer_info() == peer_info_arg:
                    peer_retry = False
            if peer_retry:
                log.info(f"Reconnecting to peer {peer_info}")
                try:
                    await server.start_client(peer_info, None, auth=auth)
                except Exception as e:
                    log.info(f"Failed to connect to {peer_info} {e}")
            await asyncio.sleep(300)

    return asyncio.create_task(connection_check())
