from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import zstd
from aiohttp import WSCloseCode, WSMessage, WSMsgType

from chia.cmds.init_funcs import chia_full_version_str
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.protocol_state_machine import message_response_ok
from chia.protocols.protocol_timing import INTERNAL_PROTOCOL_ERROR_BAN_SECONDS
from chia.protocols.shared_protocol import Capability, Handshake
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.rate_limits import RateLimiter
from chia.types.peer_info import PeerInfo
from chia.util.api_decorators import get_metadata
from chia.util.errors import Err, ProtocolError
from chia.util.ints import uint8, uint16

# Each message is prepended with LENGTH_BYTES bytes specifying the length
from chia.util.network import class_for_type, is_localhost
from chia.util.zstandard import get_decompressed_size

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
        inbound_rate_limit_percent: int,
        outbound_rate_limit_percent: int,
        local_capabilities_for_handshake: List[Tuple[uint16, str]],
        close_event=None,
        session=None,
        enable_sending_compressed: bool = False,
        compress_if_at_least_size: int = 8 * 1024,
    ):
        # Local properties
        self.ws: Any = ws
        self.local_type = local_type
        self.local_port = server_port
        self.local_capabilities_for_handshake = local_capabilities_for_handshake
        self.local_capabilities: List[Capability] = [
            Capability(x[0]) for x in local_capabilities_for_handshake if x[1] == "1"
        ]

        # Remote properties
        self.peer_host = peer_host

        peername = self.ws._writer.transport.get_extra_info("peername")

        if peername is None:
            raise ValueError(f"Was not able to get peername from {self.peer_host}")

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

        self.pending_requests: Dict[uint16, asyncio.Event] = {}
        self.request_results: Dict[uint16, Message] = {}
        self.closed = False
        self.connection_type: Optional[NodeType] = None
        if is_outbound:
            self.request_nonce: uint16 = uint16(0)
        else:
            # Different nonce to reduce chances of overlap. Each peer will increment the nonce by one for each
            # request. The receiving peer (not is_outbound), will use 2^15 to 2^16 - 1
            self.request_nonce = uint16(2**15)

        # This means that even if the other peer's boundaries for each minute are not aligned, we will not
        # disconnect. Also it allows a little flexibility.
        self.outbound_rate_limiter = RateLimiter(incoming=False, percentage_of_limit=outbound_rate_limit_percent)
        self.inbound_rate_limiter = RateLimiter(incoming=True, percentage_of_limit=inbound_rate_limit_percent)
        self.peer_capabilities: List[Capability] = []
        # Used by the Chia Seeder.
        self.version = ""
        self.protocol_version = ""

        # Used by the compressor
        self.sending_compressed_enabled = enable_sending_compressed
        self.compress_if_at_least_size = max(100, compress_if_at_least_size)
        # considering overhead, 100 is a sensible absolute minimum

    async def perform_handshake(
        self,
        network_id: str,
        protocol_version: str,
        server_port: int,
        local_type: NodeType,
    ) -> None:
        if self.is_outbound:
            outbound_handshake = make_msg(
                ProtocolMessageTypes.handshake,
                Handshake(
                    network_id,
                    protocol_version,
                    chia_full_version_str(),
                    uint16(server_port),
                    uint8(local_type.value),
                    self.local_capabilities_for_handshake,
                ),
            )
            assert outbound_handshake is not None
            await self._send_message(outbound_handshake)
            inbound_handshake_msg = await self._read_one_message()
            if inbound_handshake_msg is None:
                raise ProtocolError(Err.INVALID_HANDSHAKE)
            inbound_handshake = Handshake.from_bytes(inbound_handshake_msg.data)

            # Handle case of invalid ProtocolMessageType
            try:
                message_type: ProtocolMessageTypes = ProtocolMessageTypes(inbound_handshake_msg.type)
            except Exception:
                raise ProtocolError(Err.INVALID_HANDSHAKE)

            if message_type != ProtocolMessageTypes.handshake:
                raise ProtocolError(Err.INVALID_HANDSHAKE)

            if inbound_handshake.network_id != network_id:
                raise ProtocolError(Err.INCOMPATIBLE_NETWORK_ID)

            self.version = inbound_handshake.software_version
            self.protocol_version = inbound_handshake.protocol_version
            self.peer_server_port = inbound_handshake.server_port
            self.connection_type = NodeType(inbound_handshake.node_type)
            # "1" means capability is enabled
            self.peer_capabilities = [Capability(x[0]) for x in inbound_handshake.capabilities if x[1] == "1"]
        else:
            try:
                message = await self._read_one_message()
            except Exception:
                raise ProtocolError(Err.INVALID_HANDSHAKE)

            if message is None:
                raise ProtocolError(Err.INVALID_HANDSHAKE)

            # Handle case of invalid ProtocolMessageType
            try:
                message_type = ProtocolMessageTypes(message.type)
            except Exception:
                raise ProtocolError(Err.INVALID_HANDSHAKE)

            if message_type != ProtocolMessageTypes.handshake:
                raise ProtocolError(Err.INVALID_HANDSHAKE)

            inbound_handshake = Handshake.from_bytes(message.data)
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
                    self.local_capabilities_for_handshake,
                ),
            )
            await self._send_message(outbound_handshake)
            self.peer_server_port = inbound_handshake.server_port
            self.connection_type = NodeType(inbound_handshake.node_type)
            # "1" means capability is enabled
            self.peer_capabilities = [Capability(x[0]) for x in inbound_handshake.capabilities if x[1] == "1"]

        self.outbound_task = asyncio.create_task(self.outbound_handler())
        self.inbound_task = asyncio.create_task(self.inbound_handler())

    async def close(self, ban_time: int = 0, ws_close_code: WSCloseCode = WSCloseCode.OK, error: Optional[Err] = None):
        """
        Closes the connection, and finally calls the close_callback on the server, so the connection gets removed
        from the global list.
        """

        if self.closed:
            return None
        self.closed = True

        if error is None:
            message = b""
        else:
            message = str(int(error.value)).encode("utf-8")

        try:
            if self.inbound_task is not None:
                self.inbound_task.cancel()
            if self.outbound_task is not None:
                self.outbound_task.cancel()
            if self.ws is not None and self.ws._closed is False:
                await self.ws.close(code=ws_close_code, message=message)
            if self.session is not None:
                await self.session.close()
            if self.close_event is not None:
                self.close_event.set()
            self.cancel_pending_requests()
        except Exception:
            error_stack = traceback.format_exc()
            self.log.warning(f"Exception closing socket: {error_stack}")
            try:
                self.close_callback(self, ban_time)
            except Exception:
                error_stack = traceback.format_exc()
                self.log.error(f"Error closing1: {error_stack}")
            raise
        try:
            self.close_callback(self, ban_time)
        except Exception:
            error_stack = traceback.format_exc()
            self.log.error(f"Error closing2: {error_stack}")

    async def ban_peer_bad_protocol(self, log_err_msg: str):
        """Ban peer for protocol violation"""
        ban_seconds = INTERNAL_PROTOCOL_ERROR_BAN_SECONDS
        self.log.error(f"Banning peer for {ban_seconds} seconds: {self.peer_host} {log_err_msg}")
        await self.close(ban_seconds, WSCloseCode.PROTOCOL_ERROR, Err.INVALID_PROTOCOL_MESSAGE)

    def cancel_pending_requests(self):
        for message_id, event in self.pending_requests.items():
            try:
                event.set()
            except Exception as e:
                self.log.error(f"Failed setting event for {message_id}: {e} {traceback.format_exc()}")

    async def outbound_handler(self) -> None:
        try:
            while not self.closed:
                msg = await self.outgoing_queue.get()
                if msg is not None:
                    await self._send_message(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            expected = False
            if isinstance(e, (BrokenPipeError, ConnectionResetError, TimeoutError)):
                expected = True
            elif isinstance(e, OSError):
                if e.errno in {113}:
                    expected = True

            if expected:
                self.log.warning(f"{e} {self.peer_host}")
            else:
                error_stack = traceback.format_exc()
                self.log.error(f"Exception: {e} with {self.peer_host}")
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

    async def send_message(self, message: Message) -> bool:
        """Send message sends a message with no tracking / callback."""
        if self.closed:
            return False
        await self.outgoing_queue.put(message)
        return True

    def __getattr__(self, attr_name: str):
        # TODO KWARGS
        async def invoke(*args, **kwargs):
            timeout = 60
            if "timeout" in kwargs:
                timeout = kwargs["timeout"]
            attribute = getattr(class_for_type(self.connection_type), attr_name, None)
            if attribute is None:
                raise AttributeError(f"Node type {self.connection_type} does not have method {attr_name}")

            msg: Message = Message(uint8(getattr(ProtocolMessageTypes, attr_name).value), None, args[0])
            request_start_t = time.time()
            result = await self.send_request(msg, timeout)
            self.log.debug(
                f"Time for request {attr_name}: {self.get_peer_logging()} = {time.time() - request_start_t}, "
                f"None? {result is None}"
            )
            if result is not None:
                sent_message_type = ProtocolMessageTypes(msg.type)
                recv_message_type = ProtocolMessageTypes(result.type)
                if not message_response_ok(sent_message_type, recv_message_type):
                    # peer protocol violation
                    error_message = f"WSConnection.invoke sent message {sent_message_type.name} "
                    f"but received {recv_message_type.name}"
                    await self.ban_peer_bad_protocol(self.error_message)
                    raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [error_message])

                recv_method = getattr(class_for_type(self.local_type), recv_message_type.name)
                result = get_metadata(recv_method).message_class.from_bytes(result.data)
            return result

        return invoke

    async def send_request(self, message_no_id: Message, timeout: int) -> Optional[Message]:
        """Sends a message and waits for a response."""
        if self.closed:
            return None

        # We will wait for this event, it will be set either by the response, or the timeout
        event = asyncio.Event()

        # The request nonce is an integer between 0 and 2**16 - 1, which is used to match requests to responses
        # If is_outbound, 0 <= nonce < 2^15, else  2^15 <= nonce < 2^16
        request_id = self.request_nonce
        if self.is_outbound:
            self.request_nonce = uint16(self.request_nonce + 1) if self.request_nonce != (2**15 - 1) else uint16(0)
        else:
            self.request_nonce = (
                uint16(self.request_nonce + 1) if self.request_nonce != (2**16 - 1) else uint16(2**15)
            )

        message = Message(message_no_id.type, request_id, message_no_id.data)
        assert message.id is not None
        self.pending_requests[message.id] = event
        await self.outgoing_queue.put(message)

        # Either the result is available below or not, no need to detect the timeout error
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=timeout)

        self.pending_requests.pop(message.id)
        result: Optional[Message] = None
        if message.id in self.request_results:
            result = self.request_results[message.id]
            assert result is not None
            self.log.debug(f"<- {ProtocolMessageTypes(result.type).name} from: {self.peer_host}:{self.peer_port}")
            self.request_results.pop(message.id)

        return result

    async def send_messages(self, messages: List[Message]):
        if self.closed:
            return None
        for message in messages:
            await self.outgoing_queue.put(message)

    async def _wait_and_retry(self, msg: Message, queue: asyncio.Queue):
        try:
            await asyncio.sleep(1)
            await queue.put(msg)
        except Exception as e:
            self.log.debug(f"Exception {e} while waiting to retry sending rate limited message")
            return None

    async def _potentially_compress(self, message: Message) -> Message:
        """Returns a new message if it was compressed, otherwise the original message"""
        if message.type == ProtocolMessageTypes.wrapped_compressed.value:
            # Just return the message if already compressed
            # (happens in case of retrying a rate limited message)
            self.log.debug(
                "_potentially_compress called with already compressed message, "
                f"compressed size {len(message.data)}. OK if rate-limited before."
            )
            return message
        # If the receiver can handle compressed messages,
        # and we are configured to send them compressed,
        # and the message is large enough to be beneficial for compression (CPU-wise and space on the wire)
        # then compress it by transforming the original message into a new compressed message
        if (
            self.sending_compressed_enabled
            and Capability.CAN_DECOMPRESS_MESSAGES in self.peer_capabilities
            and len(message.data) >= self.compress_if_at_least_size
        ):
            compressed = Message(
                uint8(ProtocolMessageTypes.wrapped_compressed.value),
                message.id,
                bytes([message.type]) + bytes(zstd.compress(message.data))
                # the immediate line above is in practice a serialized WrappedCompressed
            )
            # Validating and safe-guarding
            if get_decompressed_size(compressed.data[1:]) == len(message.data):
                self.log.debug(
                    f"Message compressed for sending: was {len(message.data)} bytes, "
                    f"compressed to {len(compressed.data)}"
                )
                return compressed
            else:
                # If negative something is wrong with the data (eg. not singlesegment)
                self.log.warning(
                    f"Compression generated faulty result: #{get_decompressed_size(compressed.data[1:])}. "
                    "Sending uncompressed instead."
                )
                return message
        return message

    async def _send_message(self, message: Message):
        encoded: bytes = bytes(message)
        size = len(encoded)
        assert len(encoded) < (2 ** (LENGTH_BYTES * 8))

        # 'message' can already be compressed, if rate-limited and now retried

        message_type = ProtocolMessageTypes(message.type)
        if message_type == ProtocolMessageTypes.wrapped_compressed:
            if len(message.data) > 0:
                message_type = ProtocolMessageTypes(message.data[0])

        message_to_send = await self._potentially_compress(message)

        if message_to_send != message:
            encoded = bytes(message_to_send)
            size = len(encoded)

        if not self.outbound_rate_limiter.process_msg_and_check(
            message_to_send, self.local_capabilities, self.peer_capabilities
        ):
            if self.sending_compressed_enabled and Capability.CAN_DECOMPRESS_MESSAGES in self.peer_capabilities:
                more_info = f" (compressed: {message_to_send.type==ProtocolMessageTypes.wrapped_compressed.value})"
            else:
                more_info = ""

            if not is_localhost(self.peer_host):
                self.log.debug(
                    f"Rate limiting ourselves. message type: {message_type.name}{more_info}, peer: {self.peer_host}"
                )

                # TODO: fix this special case. This function has rate limits which are too low.
                if message_type != ProtocolMessageTypes.respond_peers:
                    asyncio.create_task(self._wait_and_retry(message_to_send, self.outgoing_queue))

                return None
            else:
                self.log.debug(
                    f"Not rate limiting ourselves. message type: {message_type.name}{more_info}, "
                    f"peer: {self.peer_host}"
                )

        await self.ws.send_bytes(encoded)
        self.log.debug(f"-> {message_type.name} to peer {self.peer_host} {self.peer_node_id}")
        self.bytes_written += size

    async def _decompress_message(self, full_message_loaded: Message, test_mode: bool = False) -> Optional[Message]:
        # This method is only called for ProtocolMessageTypes.wrapped_compressed
        # The 'test_mode' is only to make testing easier
        try:
            if Capability.CAN_DECOMPRESS_MESSAGES in self.local_capabilities and len(full_message_loaded.data) > 0:
                # Check the uncompressed size before doing the decompression (must be less than 4 GiB)
                decompressed_size = get_decompressed_size(full_message_loaded.data[1:])
                self.log.debug(
                    f"Received compressed message {ProtocolMessageTypes(full_message_loaded.data[0]).name}: "
                    f"compressed {len(full_message_loaded.data)}, decompressed {decompressed_size}"
                )
                if decompressed_size > 0 and decompressed_size < (2 ** (LENGTH_BYTES * 8)):
                    # Replace the message so it appears as if it was sent uncompressed
                    # The rate limiter has already checked the message (using the size of the compressed message)
                    full_message_loaded = Message(
                        uint8(full_message_loaded.data[0]),
                        full_message_loaded.id,
                        zstd.decompress(full_message_loaded.data[1:]),
                    )
                    return full_message_loaded
                else:
                    self.log.debug(" -> It is either not using Zstandard or it is too big")
            else:
                # We received a compressed message but we are not configured to do decompression
                # Discard this message, don't let it slip through (unless we are doing pytest)
                if len(full_message_loaded.data) > 0:
                    self.log.debug(
                        "Received compressed message "
                        f"{ProtocolMessageTypes(full_message_loaded.data[0]).name}, "
                        "but we are not configured to decompress"
                    )
                else:
                    self.log.debug("Received compressed message, but it is totally empty")
                if test_mode:
                    return full_message_loaded
        except ValueError:
            # This exception happens when trying to get the name of an out-of-range ProtocolMessageTypes for logging
            self.log.debug(
                f"Received compressed message with invalid ProtocolMessageTypes enum: {full_message_loaded.data[0]}"
            )
        return None

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
            try:
                if (
                    full_message_loaded.type == ProtocolMessageTypes.wrapped_compressed.value
                    and Capability.CAN_DECOMPRESS_MESSAGES in self.local_capabilities
                ):
                    message_type = ProtocolMessageTypes(full_message_loaded.data[0]).name
                else:
                    message_type = ProtocolMessageTypes(full_message_loaded.type).name
            except Exception:
                message_type = "Unknown"
            if not self.inbound_rate_limiter.process_msg_and_check(
                full_message_loaded, self.local_capabilities, self.peer_capabilities
            ):
                if self.local_type == NodeType.FULL_NODE and not is_localhost(self.peer_host):
                    self.log.error(
                        f"Peer has been rate limited and will be disconnected: {self.peer_host}, "
                        f"message: {message_type}"
                    )
                    # Only full node disconnects peers, to prevent abuse and crashing timelords, farmers, etc
                    asyncio.create_task(self.close(300))
                    await asyncio.sleep(3)
                    return None
                else:
                    self.log.debug(
                        f"Peer surpassed rate limit {self.peer_host}, message: {message_type}, "
                        f"port {self.peer_port} but not disconnecting"
                    )
                    # Commented so the message can potentially be decompressed
                    # return full_message_loaded
            if full_message_loaded.type == ProtocolMessageTypes.wrapped_compressed.value:
                return await self._decompress_message(full_message_loaded)
            return full_message_loaded
        elif message.type == WSMsgType.ERROR:
            self.log.error(f"WebSocket Error: {message}")
            if message.data.code == WSCloseCode.MESSAGE_TOO_BIG:
                asyncio.create_task(self.close(300))
            else:
                asyncio.create_task(self.close())
            await asyncio.sleep(3)

        else:
            self.log.error(f"Unexpected WebSocket message type: {message}")
            asyncio.create_task(self.close())
            await asyncio.sleep(3)
        return None

    # Used by the Chia Seeder.
    def get_version(self) -> str:
        return self.version

    def get_tls_version(self) -> str:
        ssl_obj = self.ws._writer.transport.get_extra_info("ssl_object")
        if ssl_obj is not None:
            return ssl_obj.version()
        else:
            return "unknown"

    def get_peer_info(self) -> Optional[PeerInfo]:
        result = self.ws._writer.transport.get_extra_info("peername")
        if result is None:
            return None
        connection_host = result[0]
        port = self.peer_server_port if self.peer_server_port is not None else self.peer_port
        return PeerInfo(connection_host, port)

    def get_peer_logging(self) -> PeerInfo:
        info: Optional[PeerInfo] = self.get_peer_info()
        if info is None:
            # in this case, we will use self.peer_host which is friendlier for logging
            port = self.peer_server_port if self.peer_server_port is not None else self.peer_port
            return PeerInfo(self.peer_host, port)
        else:
            return info
