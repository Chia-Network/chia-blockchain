import asyncio
import logging
import random
import time
import os
import concurrent
from yaml import safe_load
from typing import Any, AsyncGenerator, List, Optional, Tuple
from aiter import aiter_forker, iter_to_aiter, join_aiters, map_aiter, push_aiter
from aiter.server import start_server_aiter
from definitions import ROOT_DIR
from src.protocols.shared_protocol import Handshake, HandshakeAck, protocol_version
from src.server.connection import Connection, OnConnectFunc, PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.util import partial_func
from src.util.errors import (
    IncompatibleProtocolVersion,
    InvalidAck,
    InvalidHandshake,
    InvalidProtocolMessage,
)
from src.util.ints import uint16
from src.util.network import create_node_id

exited = False
# Each message is prepended with LENGTH_BYTES bytes specifying the length
TOTAL_RETRY_SECONDS: int = 10
RETRY_INTERVAL: int = 2

log = logging.getLogger(__name__)

config_filename = os.path.join(ROOT_DIR, "config", "config.yaml")
config = safe_load(open(config_filename, "r"))


class ChiaServer:
    # Keeps track of all connections to and from this node.
    global_connections: PeerConnections = PeerConnections([])

    # Optional listening server. You can also use this class without starting one.
    _server: Optional[asyncio.AbstractServer] = None
    _host: Optional[str] = None

    # (StreamReader, StreamWriter, NodeType) aiter, gets things from server and clients and
    # sends them through the pipeline
    _srwt_aiter: push_aiter

    # Tasks for entire server pipeline
    _pipeline_task: asyncio.Task

    # Aiter used to broadcase messages
    _outbound_aiter: push_aiter

    # Called for inbound connections after successful handshake
    _on_inbound_connect: OnConnectFunc = None

    def __init__(self, port: int, api: Any, local_type: NodeType):
        self._port = port  # TCP port to identify our node
        self._api = api  # API module that will be called from the requests
        self._local_type = local_type  # NodeType (farmer, full node, timelord, pool, harvester, wallet)
        self._srwt_aiter = push_aiter()
        self._outbound_aiter = push_aiter()
        self._pipeline_task = self.initialize_pipeline(
            self._srwt_aiter, self._api, self._port
        )
        self._node_id = create_node_id()

    async def start_server(self, host: str, on_connect: OnConnectFunc = None,) -> bool:
        """
        Launches a listening server on host and port specified, to connect to NodeType nodes. On each
        connection, the on_connect asynchronous generator will be called, and responses will be sent.
        Whenever a new TCP connection is made, a new srwt tuple is sent through the pipeline.
        """
        if self._server is not None or self._pipeline_task.done():
            return False
        self._host = host

        self._server, aiter = await start_server_aiter(
            self._port, host=None, reuse_address=True
        )
        if on_connect is not None:
            self._on_inbound_connect = on_connect

        def add_connection_type(
            srw: Tuple[asyncio.StreamReader, asyncio.StreamWriter]
        ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter, None]:
            return (srw[0], srw[1], None)

        srwt_aiter = map_aiter(add_connection_type, aiter)

        # Push all aiters that come from the server, into the pipeline
        asyncio.create_task(self._add_to_srwt_aiter(srwt_aiter))

        log.info(f"Server started on port {self._port}")
        return True

    async def start_client(
        self, target_node: PeerInfo, on_connect: OnConnectFunc = None,
    ) -> bool:
        """
        Tries to connect to the target node, adding one connection into the pipeline, if successful.
        An on connect method can also be specified, and this will be saved into the instance variables.
        """
        if self._server is not None:
            if (
                self._host == target_node.host or target_node.host == "127.0.0.1"
            ) and self._port == target_node.port:
                self.global_connections.peers.remove(target_node)
                return False
        start_time = time.time()
        succeeded: bool = False
        last_error = None
        while time.time() - start_time < TOTAL_RETRY_SECONDS and not succeeded:
            if self._pipeline_task.done():
                return False
            try:
                open_con_task = asyncio.create_task(
                    asyncio.open_connection(target_node.host, int(target_node.port))
                )
                await asyncio.wait_for(open_con_task, timeout=3)
                reader, writer = open_con_task.result()
                succeeded = True
            except (
                ConnectionRefusedError,
                TimeoutError,
                OSError,
                asyncio.TimeoutError,
            ) as e:
                last_error = e
                open_con_task.cancel()
                await asyncio.sleep(RETRY_INTERVAL)
        if not succeeded:
            log.warning(
                f"Could not connect to {target_node}. {type(last_error)}{last_error}. Aborting and removing peer."
            )
            self.global_connections.peers.remove(target_node)
            return False
        asyncio.create_task(
            self._add_to_srwt_aiter(iter_to_aiter([(reader, writer, on_connect)]))
        )
        return True

    async def _add_to_srwt_aiter(
        self,
        aiter: AsyncGenerator[
            Tuple[asyncio.StreamReader, asyncio.StreamWriter, OnConnectFunc], None
        ],
    ):
        """
        Adds all swrt from aiter into the instance variable srwt_aiter, adding them to the pipeline.
        """
        async for swrt in aiter:
            if not self._srwt_aiter.is_stopped():
                self._srwt_aiter.push(swrt)

    async def await_closed(self):
        """
        Await until the pipeline is done, after which the server and all clients are closed.
        """
        await self._pipeline_task

    def push_message(self, message: OutboundMessage):
        """
        Sends a message into the middle of the pipeline, to be sent to peers.
        """
        if not self._outbound_aiter.is_stopped():
            self._outbound_aiter.push(message)

    def close_all(self):
        """
        Starts closing all the clients and servers, by stopping the server and stopping the aiters.
        """
        self.global_connections.close_all_connections()
        self._server.close()
        if not self._outbound_aiter.is_stopped():
            self._outbound_aiter.stop()
        if not self._srwt_aiter.is_stopped():
            self._srwt_aiter.stop()

    def initialize_pipeline(self, aiter, api: Any, server_port: int) -> asyncio.Task:
        """
        A pipeline that starts with (StreamReader, StreamWriter), maps it though to
        connections, messages, executes a local API call, and returns responses.
        """

        # Maps a stream reader, writer and NodeType to a Connection object
        connections_aiter = map_aiter(
            partial_func.partial_async(
                self.stream_reader_writer_to_connection, server_port
            ),
            aiter,
        )
        # Performs a handshake with the peer
        handshaked_connections_aiter = join_aiters(
            map_aiter(self.perform_handshake, connections_aiter)
        )
        forker = aiter_forker(handshaked_connections_aiter)
        handshake_finished_1 = forker.fork(is_active=True)
        handshake_finished_2 = forker.fork(is_active=True)

        # Reads messages one at a time from the TCP connection
        messages_aiter = join_aiters(
            map_aiter(self.connection_to_message, handshake_finished_1, 100)
        )

        # Handles each message one at a time, and yields responses to send back or broadcast
        responses_aiter = join_aiters(
            map_aiter(
                partial_func.partial_async_gen(self.handle_message, api),
                messages_aiter,
                100,
            )
        )

        # Uses a forked aiter, and calls the on_connect function to send some initial messages
        # as soon as the connection is established
        on_connect_outbound_aiter = join_aiters(
            map_aiter(self.connection_to_outbound, handshake_finished_2, 100)
        )
        # Also uses the instance variable _outbound_aiter, which clients can use to send messages
        # at any time, not just on_connect.
        outbound_aiter_mapped = map_aiter(lambda x: (None, x), self._outbound_aiter)

        responses_aiter = join_aiters(
            iter_to_aiter(
                [responses_aiter, on_connect_outbound_aiter, outbound_aiter_mapped]
            )
        )

        # For each outbound message, replicate for each peer that we need to send to
        expanded_messages_aiter = join_aiters(
            map_aiter(self.expand_outbound_messages, responses_aiter, 100)
        )

        # This will run forever. Sends each message through the TCP connection, using the
        # length encoding and CBOR serialization
        async def serve_forever():
            async for connection, message in expanded_messages_aiter:
                log.info(f"-> {message.function} to peer {connection.get_peername()}")
                try:
                    await connection.send(message)
                except (ConnectionResetError, BrokenPipeError, RuntimeError) as e:
                    log.error(
                        f"Cannot write to {connection}, already closed. Error {e}."
                    )
                    self.global_connections.close(connection, True)

        # We will return a task for this, so user of start_chia_server or start_chia_client can wait until
        # the server is closed.
        return asyncio.get_running_loop().create_task(serve_forever())

    async def stream_reader_writer_to_connection(
        self,
        swrt: Tuple[asyncio.StreamReader, asyncio.StreamWriter, OnConnectFunc],
        server_port: int,
    ) -> Connection:
        """
        Maps a tuple of (StreamReader, StreamWriter, on_connect) to a Connection object,
        which also stores the type of connection (str). It is also added to the global list.
        """
        sr, sw, on_connect = swrt
        con = Connection(self._local_type, None, sr, sw, server_port, on_connect)

        log.info(f"Connection with {con.get_peername()} established")
        return con

    async def connection_to_outbound(
        self, connection: Connection
    ) -> AsyncGenerator[Tuple[Connection, OutboundMessage], None]:
        """
        Async generator which calls the on_connect async generator method, and yields any outbound messages.
        """
        for func in connection.on_connect, self._on_inbound_connect:
            if func:
                async for outbound_message in func():
                    yield connection, outbound_message

    async def perform_handshake(
        self, connection: Connection
    ) -> AsyncGenerator[Connection, None]:
        """
        Performs handshake with this new connection, and yields the connection. If the handshake
        is unsuccessful, or we already have a connection with this peer, the connection is closed,
        and nothing is yielded.
        """
        # Send handshake message
        outbound_handshake = Message(
            "handshake",
            Handshake(
                config["network_id"],
                protocol_version,
                self._node_id,
                uint16(self._port),
                self._local_type,
            ),
        )

        try:
            await connection.send(outbound_handshake)

            # Read handshake message
            full_message = await connection.read_one_message()
            inbound_handshake = Handshake(**full_message.data)
            if (
                full_message.function != "handshake"
                or not inbound_handshake
                or not inbound_handshake.node_type
            ):
                raise InvalidHandshake("Invalid handshake")

            if inbound_handshake.node_id == self._node_id:
                raise InvalidHandshake(
                    f"Should not connect to ourselves, aborting handshake."
                )

            # Makes sure that we only start one connection with each peer
            connection.node_id = inbound_handshake.node_id
            connection.peer_server_port = int(inbound_handshake.server_port)
            connection.connection_type = inbound_handshake.node_type

            if self.global_connections.have_connection(connection):
                raise InvalidHandshake(f"Duplicate connection to {connection}")

            self.global_connections.add(connection)

            # Send Ack message
            await connection.send(Message("handshake_ack", HandshakeAck()))

            # Read Ack message
            full_message = await connection.read_one_message()
            if full_message.function != "handshake_ack":
                raise InvalidAck("Invalid ack")

            if inbound_handshake.version != protocol_version:
                raise IncompatibleProtocolVersion(
                    f"Our node version {protocol_version} is not compatible with peer\
                        {connection} version {inbound_handshake.version}"
                )

            log.info(
                (
                    f"Handshake with {NodeType(connection.connection_type).name} {connection.get_peername()} "
                    f"{connection.node_id}"
                    f" established"
                )
            )
            # Only yield a connection if the handshake is succesful and the connection is not a duplicate.
            yield connection
        except (
            IncompatibleProtocolVersion,
            InvalidAck,
            InvalidHandshake,
            asyncio.IncompleteReadError,
            ConnectionResetError,
            Exception,
        ) as e:
            log.warning(f"{e}, handshake not completed. Connection not created.")
            connection.close()

    async def connection_to_message(
        self, connection: Connection
    ) -> AsyncGenerator[Tuple[Connection, Message], None]:
        """
        Async generator which yields complete binary messages from connections,
        along with a streamwriter to send back responses. On EOF received, the connection
        is removed from the global list.
        """
        try:
            while not connection.reader.at_eof():
                message = await connection.read_one_message()
                # Read one message at a time, forever
                yield (connection, message)
        except asyncio.IncompleteReadError:
            log.info(
                f"Received EOF from {connection.get_peername()}, closing connection."
            )
        except ConnectionError:
            log.warning(
                f"Connection error by peer {connection.get_peername()}, closing connection."
            )
        except (concurrent.futures._base.CancelledError, OSError, TimeoutError, asyncio.TimeoutError) as e:
            log.warning(
                f"Timeout/OSError {e} in connection with peer {connection.get_peername()}, closing connection."
            )
        finally:
            # Removes the connection from the global list, so we don't try to send things to it
            self.global_connections.close(connection, True)

    async def handle_message(
        self, pair: Tuple[Connection, Message], api: Any
    ) -> AsyncGenerator[Tuple[Connection, OutboundMessage], None]:
        """
        Async generator which takes messages, parses, them, executes the right
        api function, and yields responses (to same connection, propagated, etc).
        """
        connection, full_message = pair
        try:
            if len(full_message.function) == 0 or full_message.function.startswith("_"):
                # This prevents remote calling of private methods that start with "_"
                raise InvalidProtocolMessage(full_message.function)

            f = getattr(api, full_message.function)
            if f is None:
                raise InvalidProtocolMessage(full_message.function)

            log.info(f"<- {f.__name__} from peer {connection.get_peername()}")
            result = f(full_message.data)
            if isinstance(result, AsyncGenerator):
                async for outbound_message in result:
                    yield connection, outbound_message
            else:
                await result
        except Exception as e:
            log.error(f"Error {type(e)} {e}, closing connection {connection}")
            self.global_connections.close(connection)

    async def expand_outbound_messages(
        self, pair: Tuple[Connection, OutboundMessage]
    ) -> AsyncGenerator[Tuple[Connection, Message], None]:
        """
        Expands each of the outbound messages into it's own message.
        """
        connection, outbound_message = pair

        if connection and outbound_message.delivery_method == Delivery.RESPOND:
            if connection.connection_type == outbound_message.peer_type:
                # Only select this peer, and only if it's the right type
                yield connection, outbound_message.message
        elif outbound_message.delivery_method == Delivery.RANDOM:
            # Select a random peer.
            to_yield_single: Tuple[Connection, Message]
            typed_peers: List[Connection] = [
                peer
                for peer in self.global_connections.get_connections()
                if peer.connection_type == outbound_message.peer_type
            ]
            if len(typed_peers) == 0:
                return
            yield (random.choice(typed_peers), outbound_message.message)
        elif (
            outbound_message.delivery_method == Delivery.BROADCAST
            or outbound_message.delivery_method == Delivery.BROADCAST_TO_OTHERS
        ):
            # Broadcast to all peers.
            for peer in self.global_connections.get_connections():
                if peer.connection_type == outbound_message.peer_type:
                    if peer == connection:
                        if outbound_message.delivery_method == Delivery.BROADCAST:
                            yield (peer, outbound_message.message)
                    else:
                        yield (peer, outbound_message.message)
        elif outbound_message.delivery_method == Delivery.CLOSE:
            self.global_connections.close(connection, True)
