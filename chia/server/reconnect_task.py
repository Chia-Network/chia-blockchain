from __future__ import annotations

import asyncio
from logging import Logger

from chia.server.server import ChiaServer
from chia.types.peer_info import PeerInfo


def start_reconnect_task(server: ChiaServer, peer_info: PeerInfo, log: Logger) -> asyncio.Task[None]:
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """

    async def connection_check() -> None:
        while True:
            peer_retry = True
            for _, connection in server.all_connections.items():
                if connection.get_peer_info() == peer_info:
                    peer_retry = False
            if peer_retry:
                log.info(f"Reconnecting to peer {peer_info}")
                try:
                    await server.start_client(peer_info, None)
                except Exception as e:
                    log.info(f"Failed to connect to {peer_info} {e}")
            await asyncio.sleep(3)

    return asyncio.create_task(connection_check())
