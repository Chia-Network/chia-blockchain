from asyncio import StreamReader, StreamWriter
from asyncio import Lock
from typing import List
from src.util import cbor
from src.server.outbound_message import Message
from src.types.sized_bytes import bytes32

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 5


class Connection:
    def __init__(self, connection_type: str, sr: StreamReader, sw: StreamWriter):
        self.connection_type = connection_type
        self.reader = sr
        self.writer = sw
        socket = self.writer.get_extra_info("socket")
        self.local_host = socket.getsockname()[0]
        self.local_port = socket.getsockname()[1]
        self.peer_host, self.peer_port = self.writer.get_extra_info("peername")
        self.node_id = None

    def get_peername(self):
        return self.writer.get_extra_info("peername")

    def get_socket(self):
        return self.writer.get_extra_info("socket")

    async def send(self, message: Message):
        encoded: bytes = cbor.dumps({"function": message.function, "data": message.data})
        assert(len(encoded) < (2**(LENGTH_BYTES*8)))
        self.writer.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
        await self.writer.drain()

    async def read_one_message(self) -> Message:
        size = await self.reader.readexactly(LENGTH_BYTES)
        full_message_length = int.from_bytes(size, "big")
        full_message = await self.reader.readexactly(full_message_length)
        full_message = cbor.loads(full_message)
        return Message(full_message["function"], full_message["data"])

    def close(self):
        self.writer.close()


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

    async def already_have_connection(self, node_id: bytes32):
        ret = False
        async with self._connections_lock:
            for c in self._all_connections:
                if c.node_id == node_id:
                    ret = True
                    break
        return ret
