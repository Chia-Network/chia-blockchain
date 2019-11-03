from asyncio import StreamReader, StreamWriter
import logging
from typing import List, Any
from src.util import cbor
from src.server.outbound_message import Message, NodeType

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 5
log = logging.getLogger(__name__)


class Connection:
    def __init__(self, local_type: NodeType, connection_type: NodeType, sr: StreamReader,
                 sw: StreamWriter, server_port: int):
        self.local_type = local_type
        self.connection_type = connection_type
        self.reader = sr
        self.writer = sw
        socket = self.writer.get_extra_info("socket")
        self.local_host = socket.getsockname()[0]
        self.local_port = server_port
        self.peer_host, self.peer_port = self.writer.get_extra_info("peername")
        self.node_id = None

    def get_peername(self):
        return self.writer.get_extra_info("peername")

    def get_socket(self):
        return self.writer.get_extra_info("socket")

    async def send(self, message: Message):
        encoded: bytes = cbor.dumps({"f": message.function, "d": message.data})
        assert(len(encoded) < (2**(LENGTH_BYTES*8)))
        self.writer.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
        await self.writer.drain()

    async def read_one_message(self) -> Message:
        size = await self.reader.readexactly(LENGTH_BYTES)
        full_message_length = int.from_bytes(size, "big")
        full_message: bytes = await self.reader.readexactly(full_message_length)
        full_message_loaded: Any = cbor.loads(full_message)
        return Message(full_message_loaded["f"], full_message_loaded["d"])

    def close(self):
        self.writer.close()

    def __str__(self) -> str:
        return f"Connection({self.get_peername()})"


class PeerConnections:
    def __init__(self, all_connections: List[Connection] = []):
        self._all_connections = all_connections

    def add(self, connection: Connection) -> bool:
        for c in self._all_connections:
            if c.node_id == connection.node_id:
                return False
        self._all_connections.append(connection)
        return True

    def have_connection(self, connection: Connection) -> bool:
        for c in self._all_connections:
            if c.node_id == connection.node_id:
                return True
        return False

    def close(self, connection: Connection):
        if connection in self._all_connections:
            connection.close()
            self._all_connections.remove(connection)
            return

    def close_all_connections(self):
        for connection in self._all_connections:
            connection.close()
        self._all_connections = []

    def get_connections(self):
        return self._all_connections
