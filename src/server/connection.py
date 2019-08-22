from asyncio import StreamReader, StreamWriter
from asyncio import Lock
from typing import List


class Connection:
    def __init__(self, connection_type: str, sr: StreamReader, sw: StreamWriter):
        self.connection_type = connection_type
        self.reader = sr
        self.writer = sw

    def get_peername(self):
        return self.writer.get_extra_info("peername")


class PeerConnections:
    def __init__(self, all_connections: List[Connection] = []):
        self._connections_lock = Lock()
        self._all_connections = all_connections

    async def add(self, connection: Connection):
        async with self._connections_lock:
            self._all_connections.append(connection)

    async def remove(self, connection: Connection):
        async with self._connections_lock:
            self._all_connections.remove(connection)

    def get_lock(self):
        return self._connections_lock

    async def get_connections(self):
        return self._all_connections
