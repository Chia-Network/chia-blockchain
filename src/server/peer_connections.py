from src.server.chia_connection import ChiaConnection
from asyncio import Lock
from typing import List


class PeerConnections():
    def __init__(self, all_connections: List[ChiaConnection] = []):
        self._connections_lock = Lock()
        self._all_connections = all_connections

    async def add(self, connection: ChiaConnection):
        async with self._connections_lock:
            self._all_connections.append(connection)

    async def remove(self, connection: ChiaConnection):
        async with self._connections_lock:
            self._all_connections.remove(connection)

    async def get_lock(self):
        return self._connections_lock

    async def get_connections(self):
        return self._all_connections
