import logging
import time
import asyncio
import traceback

from typing import Any, Callable, Optional, List, Dict

from aiohttp import WSMessage, WSMsgType

from src.cmds.init import chia_full_version_str
from src.protocols.protocol_message_types import ProtocolMessageTypes
from src.protocols.shared_protocol import Handshake
from src.server.outbound_message import Message, NodeType, make_msg
from src.types.peer_info import PeerInfo
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint16, uint8
from src.util.errors import Err, ProtocolError

# Each message is prepended with LENGTH_BYTES bytes specifying the length
from src.util.network import class_for_type

# Max size 2^(8*4) which is around 4GiB
LENGTH_BYTES: int = 4


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
        peer_id,
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
        self.peer_node_id = peer_id

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

        self.inbound_task: Optional[asyncio.Task] = None
        self.outbound_task: Optional[asyncio.Task] = None
        self.active: bool = False  # once handshake is successful this will be changed to True
        self.close_event: asyncio.Event = close_event
        self.session = session
        self.close_callback = close_callback

        self.pending_requests: Dict[bytes32, asyncio.Event] = {}
        self.request_results: Dict[bytes32, Message] = {}
        self.closed = False
        self.connection_type: Optional[NodeType] = None
        self.request_nonce: uint16 = uint16(0)

    async def perform_handshake(
        self, network_id: bytes32, protocol_version: str, server_port: int, local_type: NodeType
    ):
        if self.is_outbound:
            outbound_handshake = make_msg(
                ProtocolMessageTypes.handshake,
                Handshake(
                    network_id,
                    protocol_version,
                    chia_full_version_str(),
                    uint16(server_port),
                    uint8(local_type.value),
                ),
            )
            assert outbound_handshake is not None
            await self._send_message(outbound_handshake)
            inbound_handshake_msg = await self._read_one_message()
            if inbound_handshake_msg is None:
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            inbound_handshake = Handshake.from_bytes(inbound_handshake_msg.data)
            if ProtocolMessageTypes(inbound_handshake_msg.type) != ProtocolMessageTypes.handshake:
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            if inbound_handshake.protocol_version != protocol_version:
                raise ProtocolError(Err.INCOMPATIBLE_PROTOCOL_VERSION)
            if inbound_handshake.network_id != network_id:
                raise ProtocolError(Err.INCOMPATIBLE_NETWORK_ID)

            self.peer_server_port = inbound_handshake.server_port
            self.connection_type = NodeType(inbound_handshake.node_type)

        else:
            try:
                message = await self._read_one_message()
            except Exception:
                raise ProtocolError(Err.INVALID_HANDSHAKE)

            if message is None:
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            inbound_handshake = Handshake.from_bytes(message.data)
            if ProtocolMessageTypes(message.type) != ProtocolMessageTypes.handshake:
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            if inbound_handshake.protocol_version != protocol_version:
                raise ProtocolError(Err.INCOMPATIBLE_PROTOCOL_VERSION)
            if inbound_handshake.network_id != network_id:
                raise ProtocolError(Err.INCOMPATIBLE_NETWORK_ID)
            outbound_handshake = make_msg(
                ProtocolMessageTypes.handshake,
                Handshake(
                    network_id,
                    protocol_version,
                    chia_full_version_str(),
                    uint16(server_port),
                    uint8(local_type.value),
                ),
            )
            await self._send_message(outbound_handshake)
            self.peer_server_port = inbound_handshake.server_port
            self.connection_type = NodeType(inbound_handshake.node_type)

        self.outbound_task = asyncio.create_task(self.outbound_handler())
        self.inbound_task = asyncio.create_task(self.inbound_handler())
        return True

    async def close(self):
        """
        Closes the connection, and finally calls the close_callback on the server, so the connections gets removed
        from the global list.
        """

        if self.closed:
            return
        self.closed = True

        try:
            if self.inbound_task is not None:
                self.inbound_task.cancel()
            if self.outbound_task is not None:
                self.outbound_task.cancel()
            if self.ws is not None and self.ws._closed is False:
                await self.ws.close()
            if self.session is not None:
                await self.session.close()
            if self.close_event is not None:
                self.close_event.set()
        except Exception:
            error_stack = traceback.format_exc()
            self.log.warning(f"Exception closing socket: {error_stack}")
            self.close_callback(self)
            raise
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
                message: Message = await self._read_one_message()
                if message is not None:
                    if message.id in self.pending_requests:
                        self.request_results[message.id] = message
                        event = self.pending_requests[message.id]
                        event.set()
                    else:
                        await self.incoming_queue.put((message, self))
                else:
                    continue
        except asyncio.CancelledError:
            self.log.debug("Inbound_handler task cancelled")
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    async def send_message(self, message: Message):
        """ Send message sends a message with no tracking / callback. """
        if self.closed:
            return
        await self.outgoing_queue.put(message)

    def __getattr__(self, attr_name: str):
        # TODO KWARGS
        async def invoke(*args, **kwargs):
            timeout = 60
            if "timeout" in kwargs:
                timeout = kwargs["timeout"]
            attribute = getattr(class_for_type(self.connection_type), attr_name, None)
            if attribute is None:
                raise AttributeError(f"Node type {self.connection_type} does not have method {attr_name}")

            msg = Message(uint8(getattr(ProtocolMessageTypes, attr_name).value), args[0], None)
            request_start_t = time.time()
            result = await self.create_request(msg, timeout)
            self.log.debug(
                f"Time for request {attr_name}: {self.get_peer_info()} = {time.time() - request_start_t}, "
                f"None? {result is None}"
            )
            if result is not None:
                ret_attr = getattr(class_for_type(self.local_type), ProtocolMessageTypes(result.type).name, None)

                req_annotations = ret_attr.__annotations__
                req = None
                for key in req_annotations:
                    if key == "return" or key == "peer":
                        continue
                    else:
                        req = req_annotations[key]
                assert req is not None
                result = req.from_bytes(result.data)
            return result

        return invoke

    async def create_request(self, message_no_id: Message, timeout: int) -> Optional[Message]:
        """ Sends a message and waits for a response. """
        if self.closed:
            return None

        # We will wait for this event, it will be set either by the response, or the timeout
        event = asyncio.Event()

        # The request nonce is an integer between 0 and 2**16 - 1, which is used to match requests to responses
        request_id = self.request_nonce
        self.request_nonce = uint16(self.request_nonce + 1) if self.request_nonce != (2 ** 16 - 1) else uint16(0)

        message = Message(message_no_id.type, message_no_id.data, request_id)

        self.pending_requests[message.id] = event
        await self.outgoing_queue.put(message)

        # If the timeout passes, we set the event
        async def time_out(req_id, req_timeout):
            await asyncio.sleep(req_timeout)
            if req_id in self.pending_requests:
                self.pending_requests[req_id].set()

        asyncio.create_task(time_out(message.id, timeout))
        await event.wait()

        self.pending_requests.pop(message.id)
        result: Optional[Message] = None
        if message.id in self.request_results:
            result = self.request_results[message.id]
            assert result is not None
            self.log.info(f"<- {ProtocolMessageTypes(result.type).name} from: {self.peer_host}:{self.peer_port}")
            self.request_results.pop(result.id)

        return result

    async def reply_to_request(self, response: Message):
        if self.closed:
            return
        await self.outgoing_queue.put(response)

    async def send_messages(self, messages: List[Message]):
        if self.closed:
            return
        for message in messages:
            await self.outgoing_queue.put(message)

    async def _send_message(self, message: Message):
        encoded: bytes = bytes(message)
        size = len(encoded)
        assert len(encoded) < (2 ** (LENGTH_BYTES * 8))
        await self.ws.send_bytes(encoded)
        self.log.info(f"-> {ProtocolMessageTypes(message.type).name} to peer {self.peer_host} {self.peer_node_id}")
        self.bytes_written += size

    async def _read_one_message(self) -> Optional[Message]:
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
            self.log.debug(
                f"Closing connection to {connection_type_str} {self.peer_host}:"
                f"{self.peer_server_port}/"
                f"{self.peer_port}"
            )
            asyncio.create_task(self.close())
            await asyncio.sleep(3)
        elif message.type == WSMsgType.CLOSE:
            self.log.debug(
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
            full_message_loaded: Message = Message.from_bytes(data)
            self.bytes_read += len(data)
            self.last_message_time = time.time()
            return full_message_loaded
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
