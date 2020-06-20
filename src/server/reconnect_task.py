import asyncio
import socket
from src.types.peer_info import PeerInfo


def start_reconnect_task(server, peer_info_arg, log, auth):
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """
    peer_info = PeerInfo(socket.gethostbyname(peer_info_arg.host), peer_info_arg.port)

    async def connection_check():
        while True:
            peer_retry = True

            for connection in server.global_connections.get_connections():
                if (
                    connection.get_peer_info() == peer_info
                    or connection.get_peer_info() == peer_info_arg
                ):
                    peer_retry = False

            if peer_retry:
                log.info(f"Reconnecting to peer {peer_info}")
                await server.start_client(peer_info, None, auth=auth)
            await asyncio.sleep(3)

    return asyncio.create_task(connection_check())
