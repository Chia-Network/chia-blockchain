from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
import traceback
from dataclasses import dataclass, field
from secrets import token_bytes
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

from aiohttp import ClientSession, WSCloseCode, WSMessage, WSMsgType
from aiohttp.client import ClientWebSocketResponse
from aiohttp.web import WebSocketResponse
from typing_extensions import Protocol, final

from chia.cmds.init_funcs import chia_full_version_str
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.protocol_state_machine import message_response_ok
from chia.protocols.protocol_timing import API_EXCEPTION_BAN_SECONDS, INTERNAL_PROTOCOL_ERROR_BAN_SECONDS
from chia.protocols.shared_protocol import Capability, Handshake
from chia.server.capabilities import known_active_capabilities
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.rate_limits import RateLimiter
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.api_decorators import get_metadata
from chia.util.errors import Err, ProtocolError
from chia.util.ints import uint8, uint16
from chia.util.log_exceptions import log_exceptions

# Each message is prepended with LENGTH_BYTES bytes specifying the length
from chia.util.network import class_for_type, is_localhost
from chia.util.streamable import Streamable

# Max size 2^(8*4) which is around 4GiB
LENGTH_BYTES: int = 4

WebSocket = Union[WebSocketResponse, ClientWebSocketResponse]
ConnectionCallback = Callable[["WSChiaConnection"], Awaitable[None]]


def create_default_last_message_time_dict() -> Dict[ProtocolMessageTypes, float]:
    return {message_type: -math.inf for message_type in ProtocolMessageTypes}


class ConnectionClosedCallbackProtocol(Protocol):
    def __call__(
        self,
        connection: WSChiaConnection,
        ban_time: int,
        closed_connection: bool = ...,
    ) -> None:
        ...


@final
@dataclass
class WSChiaConnection:
    """
    Represents a connection to another node. Local host and port are ours, while peer host and
    port are the host and port of the peer that we are connected to. Node_id and connection_type are
    set after the handshake is performed in this connection.
    """

    ws: WebSocket = field(repr=False)
    api: Any = field(repr=False)
    local_type: NodeType
    local_port: int
    local_capabilities_for_handshake: List[Tuple[uint16, str]] = field(repr=False)
    local_capabilities: List[Capability]
    peer_info: PeerInfo
    peer_node_id: bytes32
    log: logging.Logger = field(repr=False)

    close_callback: Optional[ConnectionClosedCallbackProtocol] = field(repr=False)
    outbound_rate_limiter: RateLimiter
    inbound_rate_limiter: RateLimiter

    # connection properties
    is_outbound: bool

    # Messaging
    received_message_callback: Optional[ConnectionCallback] = field(repr=False)
    incoming_queue: asyncio.Queue[Message] = field(default_factory=asyncio.Queue, repr=False)
    outgoing_queue: asyncio.Queue[Message] = field(default_factory=asyncio.Queue, repr=False)
    api_tasks: Dict[bytes32, asyncio.Task[None]] = field(default_factory=dict, repr=False)
    # Contains task ids of api tasks which should not be canceled
    execute_tasks: Set[bytes32] = field(default_factory=set, repr=False)

    # ChiaConnection metrics
    creation_time: float = field(default_factory=time.time)
    bytes_read: int = 0
    bytes_written: int = 0
    last_message_time: float = 0

    peer_server_port: Optional[uint16] = None
    inbound_task: Optional[asyncio.Task[None]] = field(default=None, repr=False)
    incoming_message_task: Optional[asyncio.Task[None]] = field(default=None, repr=False)
    outbound_task: Optional[asyncio.Task[None]] = field(default=None, repr=False)
    active: bool = False  # once handshake is successful this will be changed to True
    _close_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    session: Optional[ClientSession] = field(default=None, repr=False)

    pending_requests: Dict[uint16, asyncio.Event] = field(default_factory=dict, repr=False)
    request_results: Dict[uint16, Message] = field(default_factory=dict, repr=False)
    closed: bool = False
    connection_type: Optional[NodeType] = None
    request_nonce: uint16 = uint16(0)
    peer_capabilities: List[Capability] = field(default_factory=list)
    # Used by the Chia Seeder.
    version: str = field(default_factory=str)
    protocol_version: str = field(default_factory=str)

    log_rate_limit_last_time: Dict[ProtocolMessageTypes, float] = field(
        default_factory=create_default_last_message_time_dict,
        repr=False,
    )

    @classmethod
    def create(
        cls,
        local_type: NodeType,
        ws: WebSocket,
        api: Any,
        server_port: int,
        log: logging.Logger,
        is_outbound: bool,
        received_message_callback: Optional[ConnectionCallback],
        close_callback: Optional[ConnectionClosedCallbackProtocol],
        peer_id: bytes32,
        inbound_rate_limit_percent: int,
        outbound_rate_limit_percent: int,
        local_capabilities_for_handshake: List[Tuple[uint16, str]],
        session: Optional[ClientSession] = None,
    ) -> WSChiaConnection:
        assert ws._writer is not None
        peername = ws._writer.transport.get_extra_info("peername")

        if peername is None:
            raise ValueError(f"Was not able to get peername for {peer_id}")

        if is_outbound:
            request_nonce = uint16(0)
        else:
            # Different nonce to reduce chances of overlap. Each peer will increment the nonce by one for each
            # request. The receiving peer (not is_outbound), will use 2^15 to 2^16 - 1
            request_nonce = uint16(2**15)

        return cls(
            ws=ws,
            api=api,
            local_type=local_type,
            local_port=server_port,
            local_capabilities_for_handshake=local_capabilities_for_handshake,
            local_capabilities=known_active_capabilities(local_capabilities_for_handshake),
            peer_info=PeerInfo(peername[0], peername[1]),
            peer_node_id=peer_id,
            log=log,
            close_callback=close_callback,
            request_nonce=request_nonce,
            outbound_rate_limiter=RateLimiter(incoming=False, percentage_of_limit=outbound_rate_limit_percent),
            inbound_rate_limiter=RateLimiter(incoming=True, percentage_of_limit=inbound_rate_limit_percent),
            is_outbound=is_outbound,
            received_message_callback=received_message_callback,
            session=session,
        )

    def _get_extra_info(self, name: str) -> Optional[Any]:
        writer = self.ws._writer
        assert writer is not None, "websocket's ._writer is None, was .prepare() called?"
        transport = writer.transport
        if transport is None:
            return None
        try:
            return transport.get_extra_info(name)
        except AttributeError:
            # "/usr/lib/python3.11/asyncio/sslproto.py", line 91, in get_extra_info
            #   return self._ssl_protocol._get_extra_info(name, default)
            # AttributeError: 'NoneType' object has no attribute '_get_extra_info'
            return None

    async def perform_handshake(
        self,
        network_id: str,
        protocol_version: str,
        server_port: int,
        local_type: NodeType,
    ) -> None:
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
        if self.is_outbound:
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
            self.peer_capabilities = known_active_capabilities(inbound_handshake.capabilities)
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
            await self._send_message(outbound_handshake)
            self.peer_server_port = inbound_handshake.server_port
            self.connection_type = NodeType(inbound_handshake.node_type)
            # "1" means capability is enabled
            self.peer_capabilities = known_active_capabilities(inbound_handshake.capabilities)

        self.outbound_task = asyncio.create_task(self.outbound_handler())
        self.inbound_task = asyncio.create_task(self.inbound_handler())
        self.incoming_message_task = asyncio.create_task(self.incoming_message_handler())

    async def close(
        self,
        ban_time: int = 0,
        ws_close_code: WSCloseCode = WSCloseCode.OK,
        error: Optional[Err] = None,
    ) -> None:
        """
        Closes the connection, and finally calls the close_callback on the server, so the connection gets removed
        from the global list.
        """
        if self.closed:
            # always try to call the callback even for closed connections
            with log_exceptions(self.log, consume=True):
                self.log.debug(f"Closing already closed connection for {self.peer_info.host}")
                if self.close_callback is not None:
                    self.close_callback(self, ban_time, closed_connection=True)
            self._close_event.set()
            return None
        self.closed = True

        if error is None:
            message = b""
        else:
            message = str(int(error.value)).encode("utf-8")

        try:
            if self.inbound_task is not None:
                self.inbound_task.cancel()
            if self.incoming_message_task is not None:
                self.incoming_message_task.cancel()
            if self.outbound_task is not None:
                self.outbound_task.cancel()
            if self.ws is not None and self.ws.closed is False:
                await self.ws.close(code=ws_close_code, message=message)
            if self.session is not None:
                await self.session.close()
            self.cancel_pending_requests()
            self.cancel_tasks()
        except Exception:
            error_stack = traceback.format_exc()
            self.log.warning(f"Exception closing socket: {error_stack}")
            raise
        finally:
            with log_exceptions(self.log, consume=True):
                if self.close_callback is not None:
                    self.close_callback(self, ban_time, closed_connection=False)
            self._close_event.set()

    async def wait_until_closed(self) -> None:
        await self._close_event.wait()

    async def ban_peer_bad_protocol(self, log_err_msg: str) -> None:
        """Ban peer for protocol violation"""
        ban_seconds = INTERNAL_PROTOCOL_ERROR_BAN_SECONDS
        self.log.error(f"Banning peer for {ban_seconds} seconds: {self.peer_info.host} {log_err_msg}")
        await self.close(ban_seconds, WSCloseCode.PROTOCOL_ERROR, Err.INVALID_PROTOCOL_MESSAGE)

    def cancel_pending_requests(self) -> None:
        for message_id, event in self.pending_requests.items():
            try:
                event.set()
            except Exception as e:
                self.log.error(f"Failed setting event for {message_id}: {e} {traceback.format_exc()}")

    def cancel_tasks(self) -> None:
        for task_id, task in self.api_tasks.copy().items():
            if task_id in self.execute_tasks:
                continue
            task.cancel()

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
                self.log.warning(f"{e} {self.peer_info.host}")
            else:
                error_stack = traceback.format_exc()
                self.log.error(f"Exception: {e} with {self.peer_info.host}")
                self.log.error(f"Exception Stack: {error_stack}")

    async def _api_call(self, full_message: Message, task_id: bytes32) -> None:
        start_time = time.time()
        message_type = ""
        try:
            if self.received_message_callback is not None:
                await self.received_message_callback(self)
            self.log.debug(
                f"<- {ProtocolMessageTypes(full_message.type).name} from peer {self.peer_node_id} {self.peer_info.host}"
            )
            message_type = ProtocolMessageTypes(full_message.type).name

            f = getattr(self.api, message_type, None)

            if f is None:
                self.log.error(f"Non existing function: {message_type}")
                raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [message_type])

            metadata = get_metadata(function=f)
            if metadata is None:
                self.log.error(f"Peer trying to call non api function {message_type}")
                raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [message_type])

            # If api is not ready ignore the request
            if hasattr(self.api, "api_ready"):
                if self.api.api_ready is False:
                    return None

            timeout: Optional[int] = 600
            if metadata.execute_task:
                # Don't timeout on methods with execute_task decorator, these need to run fully
                self.execute_tasks.add(task_id)
                timeout = None

            if metadata.peer_required:
                coroutine = f(full_message.data, self)
            else:
                coroutine = f(full_message.data)

            async def wrapped_coroutine() -> Optional[Message]:
                try:
                    # hinting Message here is compensating for difficulty around hinting of the callbacks
                    result: Message = await coroutine
                    return result
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    tb = traceback.format_exc()
                    self.log.error(f"Exception: {e}, {self.get_peer_logging()}. {tb}")
                    raise
                return None

            response: Optional[Message] = await asyncio.wait_for(wrapped_coroutine(), timeout=timeout)
            self.log.debug(
                f"Time taken to process {message_type} from {self.peer_node_id} is "
                f"{time.time() - start_time} seconds"
            )

            if response is not None:
                response_message = Message(response.type, full_message.id, response.data)
                await self.send_message(response_message)
            # todo uncomment when enabling none response capability
            # check that this call needs a reply
            # elif message_requires_reply(ProtocolMessageTypes(full_message.type)) and self.has_capability(
            #     Capability.NONE_RESPONSE
            # ):
            #     # this peer can accept None reply's, send empty msg back, so it doesn't wait for timeout
            #     response_message = Message(uint8(ProtocolMessageTypes.none_response.value), full_message.id, b"")
            #     await self.send_message(response_message)
        except TimeoutError:
            self.log.error(f"Timeout error for: {message_type}")
        except Exception as e:
            if not self.closed:
                tb = traceback.format_exc()
                self.log.error(f"Exception: {e} {type(e)}, closing connection {self.get_peer_logging()}. {tb}")
            else:
                self.log.debug(f"Exception: {e} while closing connection")
            # TODO: actually throw one of the errors from errors.py and pass this to close
            await self.close(API_EXCEPTION_BAN_SECONDS, WSCloseCode.PROTOCOL_ERROR, Err.UNKNOWN)
        finally:
            if task_id in self.api_tasks:
                self.api_tasks.pop(task_id)
            if task_id in self.execute_tasks:
                self.execute_tasks.remove(task_id)

    async def incoming_message_handler(self) -> None:
        while True:
            message = await self.incoming_queue.get()
            task_id: bytes32 = bytes32(token_bytes(32))
            api_task = asyncio.create_task(self._api_call(message, task_id))
            self.api_tasks[task_id] = api_task

    async def inbound_handler(self) -> None:
        try:
            while not self.closed:
                message = await self._read_one_message()
                if message is not None:
                    if message.id in self.pending_requests:
                        self.request_results[message.id] = message
                        event = self.pending_requests[message.id]
                        event.set()
                    else:
                        await self.incoming_queue.put(message)
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

    async def call_api(
        self,
        request_method: Callable[..., Awaitable[Optional[Message]]],
        message: Streamable,
        timeout: int = 60,
    ) -> Any:
        if self.connection_type is None:
            raise ValueError("handshake not done yet")
        request_metadata = get_metadata(request_method)
        assert request_metadata is not None, f"ApiMetadata unavailable for {request_method}"
        attribute = getattr(class_for_type(self.connection_type), request_metadata.request_type.name, None)
        if attribute is None:
            raise AttributeError(
                f"Node type {self.connection_type} does not have method {request_metadata.request_type.name}"
            )

        request = Message(uint8(request_metadata.request_type.value), None, bytes(message))
        request_start_t = time.time()
        response = await self.send_request(request, timeout)
        self.log.debug(
            f"Time for request {request_metadata.request_type.name}: {self.get_peer_logging()} = "
            f"{time.time() - request_start_t}, None? {response is None}"
        )
        # todo or response.type == ProtocolMessageTypes.none_response.value when enabling none response
        if response is None or response.data == b"":
            return None
        sent_message_type = ProtocolMessageTypes(request.type)
        recv_message_type = ProtocolMessageTypes(response.type)
        if not message_response_ok(sent_message_type, recv_message_type):
            # peer protocol violation
            error_message = f"WSConnection.invoke sent message {sent_message_type.name} "
            f"but received {recv_message_type.name}"
            await self.ban_peer_bad_protocol(error_message)
            raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [error_message])

        recv_method = getattr(class_for_type(self.local_type), recv_message_type.name)
        receive_metadata = get_metadata(recv_method)
        assert receive_metadata is not None, f"ApiMetadata unavailable for {recv_method}"
        return receive_metadata.message_class.from_bytes(response.data)

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
            self.log.debug(
                f"<- {ProtocolMessageTypes(result.type).name} from: {self.peer_info.host}:{self.peer_info.port}"
            )
            self.request_results.pop(message.id)

        return result

    async def send_messages(self, messages: List[Message]) -> None:
        if self.closed:
            return None
        for message in messages:
            await self.outgoing_queue.put(message)

    async def _wait_and_retry(self, msg: Message) -> None:
        try:
            await asyncio.sleep(1)
            await self.outgoing_queue.put(msg)
        except Exception as e:
            self.log.debug(f"Exception {e} while waiting to retry sending rate limited message")
            return None

    async def _send_message(self, message: Message) -> None:
        encoded: bytes = bytes(message)
        size = len(encoded)
        assert len(encoded) < (2 ** (LENGTH_BYTES * 8))
        if not self.outbound_rate_limiter.process_msg_and_check(
            message, self.local_capabilities, self.peer_capabilities
        ):
            if not is_localhost(self.peer_info.host):
                message_type = ProtocolMessageTypes(message.type)
                last_time = self.log_rate_limit_last_time[message_type]
                now = time.monotonic()
                self.log_rate_limit_last_time[message_type] = now
                if now - last_time >= 60:
                    msg = f"Rate limiting ourselves. message type: {message_type.name}, peer: {self.peer_info.host}"
                    self.log.debug(msg)

                # TODO: fix this special case. This function has rate limits which are too low.
                if ProtocolMessageTypes(message.type) != ProtocolMessageTypes.respond_peers:
                    asyncio.create_task(self._wait_and_retry(message))

                return None
            else:
                self.log.debug(
                    f"Not rate limiting ourselves. message type: {ProtocolMessageTypes(message.type).name}, "
                    f"peer: {self.peer_info.host}"
                )

        await self.ws.send_bytes(encoded)
        self.log.debug(
            f"-> {ProtocolMessageTypes(message.type).name} to peer {self.peer_info.host} {self.peer_node_id}"
        )
        self.bytes_written += size

    async def _read_one_message(self) -> Optional[Message]:
        try:
            message: WSMessage = await self.ws.receive(30)
        except asyncio.TimeoutError:
            # self.ws._closed if we didn't receive a ping / pong
            if self.ws.closed:
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
                f"Closing connection to {connection_type_str} {self.peer_info.host}:"
                f"{self.peer_server_port}/"
                f"{self.peer_info.port}"
            )
            asyncio.create_task(self.close())
            await asyncio.sleep(3)
        elif message.type == WSMsgType.CLOSE:
            self.log.debug(
                f"Peer closed connection {connection_type_str} {self.peer_info.host}:"
                f"{self.peer_server_port}/"
                f"{self.peer_info.port}"
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
                message_type = ProtocolMessageTypes(full_message_loaded.type).name
            except Exception:
                message_type = "Unknown"
            if not self.inbound_rate_limiter.process_msg_and_check(
                full_message_loaded, self.local_capabilities, self.peer_capabilities
            ):
                if self.local_type == NodeType.FULL_NODE and not is_localhost(self.peer_info.host):
                    self.log.error(
                        f"Peer has been rate limited and will be disconnected: {self.peer_info.host}, "
                        f"message: {message_type}"
                    )
                    # Only full node disconnects peers, to prevent abuse and crashing timelords, farmers, etc
                    asyncio.create_task(self.close(300))
                    await asyncio.sleep(3)
                    return None
                else:
                    self.log.debug(
                        f"Peer surpassed rate limit {self.peer_info.host}, message: {message_type}, "
                        f"port {self.peer_info.port} but not disconnecting"
                    )
                    return full_message_loaded
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
        ssl_obj = self._get_extra_info("ssl_object")
        if ssl_obj is not None:
            return str(ssl_obj.version())
        else:
            return "unknown"

    def get_peer_info(self) -> Optional[PeerInfo]:
        result = self._get_extra_info("peername")
        if result is None:
            return None
        connection_host = result[0]
        port = self.peer_server_port if self.peer_server_port is not None else self.peer_info.port
        return PeerInfo(connection_host, port)

    def get_peer_logging(self) -> PeerInfo:
        info: Optional[PeerInfo] = self.get_peer_info()
        if info is None:
            # in this case, we will use self.peer_info.host which is friendlier for logging
            port = self.peer_server_port if self.peer_server_port is not None else self.peer_info.port
            return PeerInfo(self.peer_info.host, port)
        else:
            return info

    def has_capability(self, capability: Capability) -> bool:
        return capability in self.peer_capabilities
