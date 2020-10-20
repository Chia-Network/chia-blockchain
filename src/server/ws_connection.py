import logging
import time
import asyncio
import traceback
from secrets import token_bytes

from typing import Any, AsyncGenerator, Callable, Optional, List, Tuple

from aiohttp import WSMessage, WSMsgType

from src.protocols.shared_protocol import Handshake, Ping
from src.server.outbound_message import Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util import cbor
from src.util.ints import uint16
from src.util.errors import Err, ProtocolError

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 4
log = logging.getLogger(__name__)

OnConnectFunc = Optional[Callable[[], AsyncGenerator[OutboundMessage, None]]]


class WSChiaConnection:
    """
    Represents a connection to another node. Local host and port are ours, while peer host and
    port are the host and port of the peer that we are connected to. Node_id and connection_type are
    set after the handshake is performed in this connection.
    """

    def __init__(
        self,
        local_type: NodeType,
        ws: Any,  # Websocket
        server_port: int,
        log: logging.Logger,
        is_outbound: bool,
        is_feeler: bool,  # Special type of connection, that disconnects after the handshake.
        peer_host,
        incoming_queue,
        close_event=None,
        session=None,
    ):
        # Local properties
        self.ws: Any = ws
        self.local_type = local_type
        self.local_host = ""
        self.local_port = server_port
        # Remote properties
        self.peer_host = peer_host
        self.peer_server_port: Optional[int] = None
        self.peer_node_id = None

        self.log = log

        # connection properties
        self.is_outbound = is_outbound
        self.is_feeler = is_feeler

        # ChiaConnection metrics
        self.creation_time = time.time()
        self.bytes_read = 0
        self.bytes_written = 0
        self.last_message_time: float = 0

        # Messaging
        self.incoming_queue: asyncio.Queue[
            Tuple[Message, WSChiaConnection]
        ] = incoming_queue
        self.outgoing_queue: asyncio.Queue[Message] = asyncio.Queue()

        self.inbound_task = None
        self.outbound_task = None
        self.active = False  # once handshake is successful this will be changed to True
        self.close_event = close_event
        self.session = session

    async def perform_handshake(
        self, network_id, protocol_version, node_id, server_port, local_type
    ):
        self.log.info("Doing handshake")
        if self.is_outbound:
            self.log.info("Outbound handshake")
            outbound_handshake = Message(
                "handshake",
                Handshake(
                    network_id,
                    protocol_version,
                    node_id,
                    uint16(server_port),
                    local_type,
                ),
            )
            await self._send_message(outbound_handshake)
            full_message = await self._read_one_message()
            inbound_handshake = Handshake(**full_message.data)
            if (
                full_message.function != "handshake"
                or not inbound_handshake
                or not inbound_handshake.node_type
            ):
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            self.peer_node_id = inbound_handshake.node_id
            self.peer_server_port = int(inbound_handshake.server_port)
            self.connection_type = inbound_handshake.node_type
        else:
            self.log.info("Inbound handshake")
            full_message = await self._read_one_message()
            inbound_handshake = Handshake(**full_message.data)
            if (
                full_message.function != "handshake"
                or not inbound_handshake
                or not inbound_handshake.node_type
            ):
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            outbound_handshake = Message(
                "handshake",
                Handshake(
                    network_id,
                    protocol_version,
                    node_id,
                    uint16(server_port),
                    local_type,
                ),
            )
            await self._send_message(outbound_handshake)
            self.peer_node_id = inbound_handshake.node_id
            self.peer_server_port = int(inbound_handshake.server_port)
            self.connection_type = inbound_handshake.node_type

        self.outbound_task = asyncio.create_task(self.outbound_handler())
        self.inbound_task = asyncio.create_task(self.inbound_handler())
        # self.ping_task = self._initialize_ping_task()
        self.log.info("Handshake success")
        return True

    async def close(self):
        # Closes the connection. This should only be called by PeerConnections class.
        if self.ws is not None:
            await self.ws.close()
        if self.inbound_task is not None:
            self.inbound_task.cancel()
        if self.outbound_task is not None:
            self.outbound_task.cancel()
        if self.session is not None:
            await self.session.close()
        await self.closed()

    async def closed(self):
        if self.close_event is not None:
            self.close_event.set()

    async def outbound_handler(self):
        try:
            while True:
                msg = await self.outgoing_queue.get()
                if msg is not None:
                    await self._send_message(msg)
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    async def inbound_handler(self):
        try:
            while True:
                msg = await self._read_one_message()
                if msg is not None:
                    await self.incoming_queue.put((msg, self))
                else:
                    break
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    async def send_message(self, message: Message):
        await self.outgoing_queue.put(message)

    async def send_messages(self, messages: List[Message]):
        for message in messages:
            await self.outgoing_queue.put(message)

    async def _send_message(self, message):
        self.log.info(f"-> {message.function}")
        encoded: bytes = cbor.dumps({"f": message.function, "d": message.data})
        size = len(encoded)
        assert len(encoded) < (2 ** (LENGTH_BYTES * 8))
        await self.ws.send_bytes(encoded)
        self.bytes_written += size

    async def _read_one_message(self):
        try:
            # Need timeout here in case connection is closed, this allows GC to clean up
            message: WSMessage = await self.ws.receive()
            if message.type == WSMsgType.BINARY:
                data = message.data
                full_message_loaded: Any = cbor.loads(data)
                self.bytes_read += len(data)
                self.last_message_time = time.time()
                return Message(full_message_loaded["f"], full_message_loaded["d"])
            else:
                self.log.error(f"Not binary message: {message}")
                await self.close()
        except asyncio.TimeoutError:
            raise TimeoutError("self.reader.readexactly(full_message_length)")

    def get_peer_info(self):
        connection_host, connection_port = self.ws._writer.transport.get_extra_info(
            "peername"
        )
        return PeerInfo(connection_host, self.peer_server_port)
