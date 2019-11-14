from asyncio import StreamReader, StreamWriter
import logging
import time
from typing import List, Any, Optional
from src.util import cbor
from src.server.outbound_message import Message, NodeType

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 4
log = logging.getLogger(__name__)


class Connection:
    """
    Represents a connection to another node. Local host and port are ours, while peer host and
    port are the host and port of the peer that we are connected to. Node_id and connection_type are
    set after the handshake is performed in this connection.
    """
    def __init__(self, local_type: NodeType, connection_type: Optional[NodeType], sr: StreamReader,
                 sw: StreamWriter, server_port: int):
        self.local_type = local_type
        self.connection_type = connection_type
        self.reader = sr
        self.writer = sw
        socket = self.writer.get_extra_info("socket")
        socket.settimeout(None)
        self.local_host = socket.getsockname()[0]
        self.local_port = server_port
        self.peer_host = self.writer.get_extra_info("peername")[0]
        self.peer_port = self.writer.get_extra_info("peername")[1]
        self.peer_server_port: Optional[int] = None
        self.node_id = None

        # Connection metrics
        self.creation_type = time.time()
        self.bytes_read = 0
        self.bytes_written = 0

    def get_peername(self):
        return self.writer.get_extra_info("peername")

    def get_socket(self):
        return self.writer.get_extra_info("socket")

    async def send(self, message: Message):
        encoded: bytes = cbor.dumps({"f": message.function, "d": message.data})
        assert(len(encoded) < (2**(LENGTH_BYTES*8)))
        self.writer.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
        await self.writer.drain()
        self.bytes_written += (LENGTH_BYTES + len(encoded))

    async def read_one_message(self) -> Message:
        size = await self.reader.readexactly(LENGTH_BYTES)
        full_message_length = int.from_bytes(size, "big")
        full_message: bytes = await self.reader.readexactly(full_message_length)
        full_message_loaded: Any = cbor.loads(full_message)
        self.bytes_read += (LENGTH_BYTES + full_message_length)
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
