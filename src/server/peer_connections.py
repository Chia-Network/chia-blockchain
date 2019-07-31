from src.server.chia_connection import ChiaConnection
from asyncio import Lock
from typing import List


class PeerConnections():
    def __init__(self, all_connections: List[ChiaConnection] = []):
        self.connections_lock_ = Lock()
        self.all_connections_ = all_connections

    async def add(self, connection: ChiaConnection):
        async with self.connections_lock_:
            self.all_connections_.append(connection)

    async def remove(self, connection: ChiaConnection):
        async with self.connections_lock_:
            self.all_connections_.remove(connection)

    async def get_lock(self):
        return self.connections_lock_

    async def get_connections(self):
        return self.all_connections_
