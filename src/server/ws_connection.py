import logging
import time
import asyncio
import traceback
from secrets import token_bytes

from typing import Any, AsyncGenerator, Callable, Optional, List, Dict

from aiohttp import WSMessage, WSMsgType

from src.protocols.shared_protocol import Handshake
from src.server.outbound_message import Message, NodeType, OutboundMessage, Payload
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util import cbor
from src.util.ints import uint16
from src.util.errors import Err, ProtocolError

# Each message is prepended with LENGTH_BYTES bytes specifying the length
from src.util.network import class_for_type

LENGTH_BYTES: int = 4

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
        close_callback: Callable,
        close_event=None,
        session=None,
    ):
        # Local properties
        self.ws: Any = ws
        self.local_type = local_type
        self.local_port = server_port
        # Remote properties
        self.peer_host = peer_host

        peername = self.ws._writer.transport.get_extra_info("peername")
        if peername is None:
            raise ValueError(f"Was not able to get peername from {self.ws_witer} at {self.peer_host}")

        connection_port = peername[1]
        self.peer_port = connection_port
        self.peer_server_port: Optional[uint16] = None
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
        self.incoming_queue: asyncio.Queue = incoming_queue
        self.outgoing_queue: asyncio.Queue = asyncio.Queue()

        self.inbound_task = None
        self.outbound_task = None
        self.active = False  # once handshake is successful this will be changed to True
        self.close_event = close_event
        self.session = session
        self.close_callback = close_callback

        self.pending_requests: Dict[bytes32, asyncio.Event] = {}
        self.request_results: Dict[bytes32, Payload] = {}
        self.closed = False
        self.connection_type = None

    async def perform_handshake(self, network_id, protocol_version, node_id, server_port, local_type):
        if self.is_outbound:
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
            payload = Payload(outbound_handshake, None)
            await self._send_message(payload)
            payload = await self._read_one_message()
            inbound_handshake = Handshake(**payload.msg.data)
            if payload.msg.function != "handshake" or not inbound_handshake or not inbound_handshake.node_type:
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            self.peer_node_id = inbound_handshake.node_id
            self.peer_server_port = int(inbound_handshake.server_port)
            self.connection_type = inbound_handshake.node_type

        else:
            payload = await self._read_one_message()
            inbound_handshake = Handshake(**payload.msg.data)
            if payload.msg.function != "handshake" or not inbound_handshake or not inbound_handshake.node_type:
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
            payload = Payload(outbound_handshake, None)
            await self._send_message(payload)
            self.peer_node_id = inbound_handshake.node_id
            self.peer_server_port = int(inbound_handshake.server_port)
            self.connection_type = inbound_handshake.node_type

        if self.peer_node_id == node_id:
            raise ProtocolError(Err.SELF_CONNECTION)

        self.outbound_task = asyncio.create_task(self.outbound_handler())
        self.inbound_task = asyncio.create_task(self.inbound_handler())
        return True

    async def close(self):
        # Closes the connection
        if self.closed:
            return
        self.closed = True
        if self.ws is not None and self.ws._closed is False:
            await self.ws.close()
        if self.inbound_task is not None:
            self.inbound_task.cancel()
        if self.outbound_task is not None:
            self.outbound_task.cancel()
        if self.session is not None:
            await self.session.close()
        if self.close_event is not None:
            self.close_event.set()
        self.close_callback(self)

    async def outbound_handler(self):
        try:
            while not self.closed:
                msg = await self.outgoing_queue.get()
                if msg is not None:
                    await self._send_message(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    async def inbound_handler(self):
        try:
            while not self.closed:
                payload: Payload = await self._read_one_message()
                if payload is not None:
                    if payload.id in self.pending_requests:
                        self.request_results[payload.id] = payload
                        event = self.pending_requests[payload.id]
                        event.set()
                    else:
                        await self.incoming_queue.put((payload, self))
                else:
                    continue
        except asyncio.CancelledError:
            self.log.info("task canceled")
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    async def send_message(self, message: Message):
        """ Send message sends a message with no tracking / callback. """
        if self.closed:
            return
        payload = Payload(message, None)
        await self.outgoing_queue.put(payload)

    def __getattr__(self, attr_name: str):
        # TODO KWARGS
        async def invoke(*args, **kwargs):
            attribute = getattr(class_for_type(self.connection_type), attr_name, None)
            if attribute is None:
                raise AttributeError(f"bad attribute {attr_name}")

            msg = Message(attr_name, args[0])
            result = await self.create_request(msg, 60)
            if result is not None:
                ret_attr = getattr(class_for_type(self.local_type), result.function, None)

                req_annotations = ret_attr.__annotations__
                req = None
                for key in req_annotations:
                    if key == "return" or key == "peer":
                        continue
                    else:
                        req = req_annotations[key]
                assert req is not None
                result = req(**result.data)
            return result

        return invoke

    async def create_request(self, message: Message, timeout: int = 15):
        """ Sends a message and waits for a response. """
        if self.closed:
            return None

        event = asyncio.Event()
        payload = Payload(message, token_bytes(8))

        self.pending_requests[payload.id] = event
        await self.outgoing_queue.put(payload)

        async def time_out(req_id, req_timeout):
            await asyncio.sleep(req_timeout)
            if req_id in self.pending_requests:
                self.pending_requests[req_id].set()

        asyncio.create_task(time_out(payload.id, timeout))
        await event.wait()

        self.pending_requests.pop(payload.id)
        result: Optional[Message] = None
        if payload.id in self.request_results:
            result_payload: Payload = self.request_results[payload.id]
            result = result_payload.msg
            self.log.info(f"<- {result_payload.msg.function} from: {self.peer_host}:{self.peer_port}")
            self.request_results.pop(payload.id)

        return result

    async def reply_to_request(self, response: Payload):
        if self.closed:
            return
        await self.outgoing_queue.put(response)

    async def send_messages(self, messages: List[Message]):
        if self.closed:
            return
        for message in messages:
            payload = Payload(message, None)
            await self.outgoing_queue.put(payload)

    async def _send_message(self, payload: Payload):
        encoded: bytes = cbor.dumps({"f": payload.msg.function, "d": payload.msg.data, "i": payload.id})
        size = len(encoded)
        assert len(encoded) < (2 ** (LENGTH_BYTES * 8))
        await self.ws.send_bytes(encoded)
        self.log.info(f"-> {payload.msg.function} to peer {self.peer_host} {self.peer_node_id}")
        self.bytes_written += size

    async def _read_one_message(self) -> Optional[Payload]:
        try:
            message: WSMessage = await self.ws.receive(30)
        except asyncio.TimeoutError:
            # self.ws._closed if we didn't receive a ping / pong
            if self.ws._closed:
                asyncio.create_task(self.close())
                await asyncio.sleep(3)
                return None
            return None

        if self.connection_type is not None:
            connection_type_str = NodeType(self.connection_type).name.lower()
        else:
            connection_type_str = ""
        if message.type == WSMsgType.CLOSING:
            self.log.info(
                f"Closing connection to {connection_type_str} {self.peer_host}:"
                f"{self.peer_server_port}/"
                f"{self.peer_port}"
            )
        elif message.type == WSMsgType.CLOSE:
            self.log.info(
                f"Peer closed connection {connection_type_str} {self.peer_host}:"
                f"{self.peer_server_port}/"
                f"{self.peer_port}"
            )
            asyncio.create_task(self.close())
            await asyncio.sleep(3)
        elif message.type == WSMsgType.CLOSED:
            if not self.closed:
                asyncio.create_task(self.close())
                await asyncio.sleep(3)
                return None
        elif message.type == WSMsgType.BINARY:
            data = message.data
            full_message_loaded: Any = cbor.loads(data)
            self.bytes_read += len(data)
            self.last_message_time = time.time()
            msg = Message(full_message_loaded["f"], full_message_loaded["d"])
            payload_id = full_message_loaded["i"]
            payload = Payload(msg, payload_id)
            return payload
        else:
            self.log.error(f"Unexpected WebSocket message type: {message}")
            asyncio.create_task(self.close())
            await asyncio.sleep(3)
        return None

    def get_peer_info(self) -> Optional[PeerInfo]:
        result = self.ws._writer.transport.get_extra_info("peername")
        if result is None:
            return None
        connection_host = result[0]
        port = self.peer_server_port if self.peer_server_port is not None else self.peer_port
        return PeerInfo(connection_host, port)
