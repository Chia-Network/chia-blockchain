import logging
import time
import asyncio
import socket
from typing import Any, AsyncGenerator, Callable, List, Optional

from src.server.outbound_message import Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.util import cbor
from src.util.ints import uint16
from src.server.introducer_peers import IntroducerPeers
from src.util.errors import Err, ProtocolError

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 4
log = logging.getLogger(__name__)

OnConnectFunc = Optional[Callable[[], AsyncGenerator[OutboundMessage, None]]]


class ChiaConnection:
    """
    Represents a connection to another node. Local host and port are ours, while peer host and
    port are the host and port of the peer that we are connected to. Node_id and connection_type are
    set after the handshake is performed in this connection.
    """

    def __init__(
        self,
        local_type: NodeType,
        connection_type: Optional[NodeType],
        sr: asyncio.StreamReader,
        sw: asyncio.StreamWriter,
        server_port: int,
        on_connect: OnConnectFunc,
        log: logging.Logger,
        is_outbound: bool,
        # Special type of connection, that disconnects after the handshake.
        is_feeler: bool,
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
        self.is_outbound = is_outbound
        self.is_feeler = is_feeler

        # ChiaConnection metrics
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
        try:
            # Need timeout here in case connection is closed, this allows GC to clean up
            await asyncio.wait_for(self.writer.drain(), timeout=10 * 60)
        except asyncio.TimeoutError:
            raise TimeoutError("self.writer.drain()")
        self.bytes_written += LENGTH_BYTES + len(encoded)

    async def read_one_message(self) -> Message:
        size: bytes = b""
        try:
            # Need timeout here in case connection is closed, this allows GC to clean up
            size = await asyncio.wait_for(
                self.reader.readexactly(LENGTH_BYTES), timeout=10 * 60
            )
        except asyncio.TimeoutError:
            raise TimeoutError("self.reader.readexactly(LENGTH_BYTES)")

        full_message_length = int.from_bytes(size, "big")

        full_message: bytes = b""
        try:
            # Need timeout here in case connection is closed, this allows GC to clean up
            full_message = await asyncio.wait_for(
                self.reader.readexactly(full_message_length), timeout=10 * 60
            )
        except asyncio.TimeoutError:
            raise TimeoutError("self.reader.readexactly(full_message_length)")

        full_message_loaded: Any = cbor.loads(full_message)
        self.bytes_read += LENGTH_BYTES + full_message_length
        self.last_message_time = time.time()
        return Message(full_message_loaded["f"], full_message_loaded["d"])

    def close(self):
        # Closes the connection. This should only be called by PeerConnections class.
        self.writer.close()

    def __str__(self) -> str:
        if self.peer_server_port is not None:
            return f"Connection({self.get_peername()}, server_port {self.peer_server_port})"
        return f"Connection({self.get_peername()})"


class PeerConnections:
    def __init__(
        self, local_type: NodeType, all_connections: List[ChiaConnection] = []
    ):
        self._all_connections = all_connections
        self.local_type = local_type
        self.introducer_peers = None
        self.connection = None
        if local_type == NodeType.INTRODUCER:
            self.introducer_peers = IntroducerPeers()
            for c in all_connections:
                if c.connection_type == NodeType.FULL_NODE:
                    self.introducer_peers.add(c.get_peer_info())
        self.state_changed_callback: Optional[Callable] = None
        self.full_node_peers_callback: Optional[Callable] = None
        self.wallet_callback: Optional[Callable] = None
        self.max_inbound_count = 0

    def set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    def set_full_node_peers_callback(self, callback: Callable):
        self.full_node_peers_callback = callback

    def set_wallet_callback(self, callback: Callable):
        self.wallet_callback = callback

    def _state_changed(self, state: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(state)

    def add(self, connection: ChiaConnection) -> bool:
        if not connection.is_outbound:
            if (
                connection.connection_type is not None
                and not self.accept_inbound_connections(connection.connection_type)
            ):
                raise ProtocolError(Err.MAX_INBOUND_CONNECTIONS_REACHED)

        for c in self._all_connections:
            if c.node_id == connection.node_id:
                raise ProtocolError(Err.DUPLICATE_CONNECTION, [False])
        self._all_connections.append(connection)

        if connection.connection_type == NodeType.FULL_NODE:
            self._state_changed("add_connection")
            if self.introducer_peers is not None:
                return self.introducer_peers.add(connection.get_peer_info())
        self._state_changed("add_connection")
        return True

    def close(self, connection: ChiaConnection, keep_peer: bool = False):
        if connection in self._all_connections:
            info = connection.get_peer_info()
            self._all_connections.remove(connection)
            connection.close()
            self._state_changed("close_connection")
            if not keep_peer:
                if self.introducer_peers is not None:
                    self.introducer_peers.remove(info)

    def close_all_connections(self):
        for connection in self._all_connections:
            connection.close()
            self._state_changed("close_connection")
        self._all_connections = []
        if self.local_type == NodeType.INTRODUCER:
            self.introducer_peers = IntroducerPeers()

    def get_local_peerinfo(self) -> Optional[PeerInfo]:
        ip = None
        port = None
        for c in self._all_connections:
            if c.connection_type == NodeType.FULL_NODE:
                port = c.local_port
                break
        if port is None:
            return None

        # https://stackoverflow.com/a/28950776
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("introducer.beta.chia.net", 8444))
                ip = s.getsockname()[0]
            except Exception:
                ip = None
        if ip is None:
            return None
        return PeerInfo(str(ip), uint16(port))

    def get_connections(self):
        return self._all_connections

    def get_full_node_connections(self):
        return list(filter(ChiaConnection.get_peer_info, self._all_connections))

    def get_full_node_peerinfos(self):
        return list(
            filter(None, map(ChiaConnection.get_peer_info, self._all_connections))
        )

    async def successful_handshake(self, connection):
        if connection.connection_type == NodeType.FULL_NODE:
            if connection.is_outbound:
                if self.full_node_peers_callback is not None:
                    self.full_node_peers_callback(
                        "mark_tried",
                        connection.get_peer_info(),
                    )
                if self.wallet_callback is not None:
                    self.wallet_callback(
                        "make_tried",
                        connection.get_peer_info(),
                    )
                if connection.is_feeler:
                    connection.close()
                    self.close(connection)
                    return
                # Request peers after handshake.
                if connection.local_type == NodeType.FULL_NODE:
                    await connection.send(Message("request_peers", ""))
            else:
                if self.full_node_peers_callback is not None:
                    self.full_node_peers_callback(
                        "new_inbound_connection",
                        connection.get_peer_info(),
                    )
        yield connection

    def failed_handshake(self, connection, e):
        if connection.connection_type == NodeType.FULL_NODE and connection.is_outbound:
            message = "mark_attempted"
            if isinstance(e, ProtocolError) and (
                e.code == Err.DUPLICATE_CONNECTION or e.code == Err.SELF_CONNECTION
            ):
                # Updates last try timestamp, but doesn't count it as a failure. 
                message = "mark_attempted_soft"

            if self.full_node_peers_callback is not None:
                self.full_node_peers_callback(
                    message, connection.get_peer_info(),
                )
            if self.wallet_callback is not None:
                self.wallet_callback(
                    message, connection.get_peer_info(),
                )

    def failed_connection(self, peer_info):
        if self.full_node_peers_callback is not None:
            self.full_node_peers_callback(
                "mark_attempted",
                peer_info,
            )
        if self.wallet_callback is not None:
            self.wallet_callback(
                "mark_attempted",
                peer_info,
            )

    def update_connection_time(self, connection):
        if connection.connection_type == NodeType.FULL_NODE and connection.is_outbound:
            if self.full_node_peers_callback is not None:
                self.full_node_peers_callback(
                    "update_connection_time",
                    connection.get_peer_info(),
                )
            if self.wallet_callback is not None:
                self.wallet_callback(
                    "update_connection_time",
                    connection.get_peer_info(),
                )

    # Functions related to outbound and inbound connections for the full node.
    def count_outbound_connections(self):
        return len(self.get_outbound_connections())

    def get_outbound_connections(self):
        return [
            conn
            for conn in self._all_connections
            if conn.is_outbound and conn.connection_type == NodeType.FULL_NODE
        ]

    def accept_inbound_connections(self, node_type: NodeType):
        if not self.local_type == NodeType.FULL_NODE:
            return True
        inbound_count = len(
            [
                conn
                for conn in self._all_connections
                if not conn.is_outbound and conn.connection_type == node_type
            ]
        )
        if node_type == NodeType.FULL_NODE:
            return inbound_count < self.max_inbound_count
        if node_type == NodeType.WALLET:
            return inbound_count < 20
        return inbound_count < 10
