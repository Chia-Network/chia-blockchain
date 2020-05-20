import logging
import random
import time
from asyncio import StreamReader, StreamWriter
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from src.server.outbound_message import Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util import cbor
from src.util.ints import uint16, uint64

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 4
log = logging.getLogger(__name__)

OnConnectFunc = Optional[Callable[[], AsyncGenerator[OutboundMessage, None]]]


class Connection:
    """
    Represents a connection to another node. Local host and port are ours, while peer host and
    port are the host and port of the peer that we are connected to. Node_id and connection_type are
    set after the handshake is performed in this connection.
    """

    def __init__(
        self,
        local_type: NodeType,
        connection_type: Optional[NodeType],
        sr: StreamReader,
        sw: StreamWriter,
        server_port: int,
        on_connect: OnConnectFunc,
        log: logging.Logger,
    ):
        self.local_type = local_type
        self.connection_type = connection_type
        self.reader = sr
        self.writer = sw
        socket = self.writer.get_extra_info("socket")
        self.local_host = socket.getsockname()[0]
        self.local_port = server_port
        self.peer_host = self.writer.get_extra_info("peername")[0]
        self.peer_port = self.writer.get_extra_info("peername")[1]
        self.peer_server_port: Optional[int] = None
        self.node_id = None
        self.on_connect = on_connect
        self.log = log

        # Connection metrics
        self.creation_time = time.time()
        self.bytes_read = 0
        self.bytes_written = 0
        self.last_message_time: float = 0
        self._cached_peer_name = self.writer.get_extra_info("peername")

    def get_peername(self):
        return self._cached_peer_name

    def get_socket(self):
        return self.writer.get_extra_info("socket")

    def get_peer_info(self) -> Optional[PeerInfo]:
        if not self.peer_server_port:
            return None
        return PeerInfo(self.peer_host, uint16(self.peer_server_port))

    def get_last_message_time(self) -> float:
        return self.last_message_time

    def is_closing(self) -> bool:
        return self.writer.is_closing()

    async def send(self, message: Message):
        encoded: bytes = cbor.dumps({"f": message.function, "d": message.data})
        assert len(encoded) < (2 ** (LENGTH_BYTES * 8))
        self.writer.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
        await self.writer.drain()
        self.bytes_written += LENGTH_BYTES + len(encoded)

    async def read_one_message(self) -> Message:
        size = await self.reader.readexactly(LENGTH_BYTES)
        full_message_length = int.from_bytes(size, "big")
        full_message: bytes = await self.reader.readexactly(full_message_length)
        full_message_loaded: Any = cbor.loads(full_message)
        self.bytes_read += LENGTH_BYTES + full_message_length
        self.last_message_time = time.time()
        return Message(full_message_loaded["f"], full_message_loaded["d"])

    def close(self):
        self.writer.close()

    def __str__(self) -> str:
        if self.peer_server_port is not None:
            return f"Connection({self.get_peername()}, server_port {self.peer_server_port})"
        return f"Connection({self.get_peername()})"


class PeerConnections:
    def __init__(self, all_connections: List[Connection] = []):
        self._all_connections = all_connections
        # Only full node peers are added to `peers`
        self.peers = Peers()
        for c in all_connections:
            if c.connection_type == NodeType.FULL_NODE:
                self.peers.add(c.get_peer_info())
        self.state_changed_callback: Optional[Callable] = None

    def set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    def _state_changed(self, state: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(state)

    def add(self, connection: Connection) -> bool:
        for c in self._all_connections:
            if c.node_id == connection.node_id:
                return False
        self._all_connections.append(connection)

        if connection.connection_type == NodeType.FULL_NODE:
            self._state_changed("add_connection")
            return self.peers.add(connection.get_peer_info())
        self._state_changed("add_connection")
        return True

    def close(self, connection: Connection, keep_peer: bool = False):
        if connection in self._all_connections:
            info = connection.get_peer_info()
            self._all_connections.remove(connection)
            connection.close()
            self._state_changed("close_connection")
            if not keep_peer:
                self.peers.remove(info)

    def close_all_connections(self):
        for connection in self._all_connections:
            connection.close()
            self._state_changed("close_connection")
        self._all_connections = []
        self.peers = Peers()

    def get_connections(self):
        return self._all_connections

    def get_full_node_connections(self):
        return list(filter(Connection.get_peer_info, self._all_connections))

    def get_full_node_peerinfos(self):
        return list(filter(None, map(Connection.get_peer_info, self._all_connections)))

    def get_unconnected_peers(self, max_peers=0, recent_threshold=9999999):
        connected = self.get_full_node_peerinfos()
        peers = self.peers.get_peers(recent_threshold=recent_threshold)
        unconnected = list(filter(lambda peer: peer not in connected, peers))
        if not max_peers:
            max_peers = len(unconnected)
        return unconnected[:max_peers]


class Peers:
    """
    Has the list of known full node peers that are already connected or may be
    connected to, and the time that they were last added.
    """

    def __init__(self):
        self._peers: List[PeerInfo] = []
        self.time_added: Dict[bytes32, uint64] = {}

    def add(self, peer: Optional[PeerInfo]) -> bool:
        if peer is None or not peer.port:
            return False
        if peer not in self._peers:
            self._peers.append(peer)
        self.time_added[peer.get_hash()] = uint64(int(time.time()))
        return True

    def remove(self, peer: Optional[PeerInfo]) -> bool:
        if peer is None or not peer.port:
            return False
        try:
            self._peers.remove(peer)
            return True
        except ValueError:
            return False

    def get_peers(
        self, max_peers: int = 0, randomize: bool = False, recent_threshold=9999999
    ) -> List[PeerInfo]:
        target_peers = [
            peer
            for peer in self._peers
            if time.time() - self.time_added[peer.get_hash()] < recent_threshold
        ]
        if not max_peers or max_peers > len(target_peers):
            max_peers = len(target_peers)
        if randomize:
            random.shuffle(target_peers)
        return target_peers[:max_peers]
