import asyncio
import socket
import logging
from src.types.peer_info import PeerInfo


log = logging.getLogger(__name__)


def start_reconnect_task(server, peer_info_arg, log, auth):
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """
    peer_info = PeerInfo(socket.gethostbyname(peer_info_arg.host), peer_info_arg.port)

    async def connection_check():
        while True:
            peer_retry = True
            for id, connection in server.all_connections.items():
                if (
                    connection.get_peer_info() == peer_info
                    or connection.get_peer_info() == peer_info_arg
                ):
                    log.info(f"Not reconnecting to peer {peer_info}")
                    peer_retry = False

            if peer_retry:
                log.info(f"Reconnecting to peer {peer_info}")
                try:
                    await server.start_client(peer_info, None, auth=auth)
                except Exception as e:
                    log.info(f"Failed to connect to {peer_info} {e}")
            await asyncio.sleep(3)

    return asyncio.create_task(connection_check())
