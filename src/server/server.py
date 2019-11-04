import logging
import asyncio
import random
from typing import Tuple, AsyncGenerator, Callable, Optional, List, Any, Dict
from aiter.server import start_server_aiter
from aiter.map_aiter import map_aiter
from aiter.join_aiters import join_aiters
from aiter.iter_to_aiter import iter_to_aiter
from aiter.aiter_forker import aiter_forker
from aiter.push_aiter import push_aiter
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.server.connection import Connection, PeerConnections
from src.server.outbound_message import OutboundMessage, Delivery, Message, NodeType
from src.protocols.shared_protocol import Handshake, HandshakeAck, protocol_version
from src.util import partial_func
from src.util.errors import InvalidHandshake, IncompatibleProtocolVersion, DuplicateConnection, InvalidAck
from src.util.network import create_node_id

exited = False
# Each message is prepended with LENGTH_BYTES bytes specifying the length
TOTAL_RETRY_SECONDS: int = 10
RETRY_INTERVAL: int = 2

log = logging.getLogger(__name__)


class ChiaServer:
    # Keeps track of all connections to and from this node.
    global_connections: PeerConnections = PeerConnections([])

    # Optional listening server. You can also use this class without starting one.
    _server: Optional[asyncio.AbstractServer] = None

    # (StreamReader, StreamWriter, NodeType) aiter, gets things from server and clients and
    # sends them through the pipeline
    _srwt_aiter: push_aiter

    # Tasks for entire server pipeline
    _pipeline_task: asyncio.Task

    # Aiter used to broadcase messages
    _outbound_aiter: push_aiter

    # These will get called after a handshake is performed
    _on_connect_callbacks: Dict[bytes32, Callable] = {}
    _on_connect_generic_callback: Optional[Callable] = None

    def __init__(self, port: int, api: Any, local_type: NodeType):
        self._port = port  # TCP port to identify our node
        self._api = api  # API module that will be called from the requests
        self._local_type = local_type  # NodeType (farmer, full node, timelord, pool, plotter, wallet)
        self._srwt_aiter = push_aiter()
        self._outbound_aiter = push_aiter()
        self._pipeline_task = self.initialize_pipeline(self._srwt_aiter, self._api, self._port)

    async def start_server(self, host: str,
                           on_connect: Optional[Callable[[], AsyncGenerator[OutboundMessage, None]]] = None) -> bool:
        """
        Launches a listening server on host and port specified, to connect to NodeType nodes. On each
        connection, the on_connect asynchronous generator will be called, and responses will be sent.
        Whenever a new TCP connection is made, a new srwt tuple is sent through the pipeline.
        """
        if self._server is not None:
            return False

        self._server, aiter = await start_server_aiter(self._port, host=None, reuse_address=True)
        if on_connect is not None:
            self._on_connect_generic_callback = on_connect

        def add_connection_type(srw: Tuple[asyncio.StreamReader, asyncio.StreamWriter]) -> \
                Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            return (srw[0], srw[1])
        srwt_aiter = map_aiter(add_connection_type, aiter)

        # Push all aiters that come from the server, into the pipeline
        asyncio.create_task(self._add_to_srwt_aiter(srwt_aiter))

        log.info(f"Server started on port {self._port}")
        return True

    async def start_client(self, target_node: PeerInfo,
                           on_connect: Optional[Callable[[], AsyncGenerator[OutboundMessage, None]]] = None) -> bool:
        """
        Tries to connect to the target node, adding one connection into the pipeline, if successful.
        An on connect method can also be specified, and this will be saved into the instance variables.
        """
        total_time: int = 0
        succeeded: bool = False
        for _ in range(0, TOTAL_RETRY_SECONDS, RETRY_INTERVAL):
            try:
                reader, writer = await asyncio.open_connection(target_node.host, target_node.port)
                succeeded = True
                break
            except ConnectionRefusedError:
                log.warning(f"Connection to {target_node.host}:{target_node.port} refused.")
                await asyncio.sleep(RETRY_INTERVAL)
                total_time += RETRY_INTERVAL
                continue

        if not succeeded:
            return False
        if on_connect is not None:
            self._on_connect_callbacks[target_node.node_id] = on_connect
        asyncio.create_task(self._add_to_srwt_aiter(iter_to_aiter([(reader, writer)])))
        return True

    async def _add_to_srwt_aiter(self, aiter: AsyncGenerator[Tuple[asyncio.StreamReader, asyncio.StreamWriter], None]):
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
        connections_aiter = map_aiter(partial_func.partial_async(self.stream_reader_writer_to_connection,
                                                                 server_port), aiter)
        # Performs a handshake with the peer
        handshaked_connections_aiter = join_aiters(map_aiter(self.perform_handshake, connections_aiter))
        forker = aiter_forker(handshaked_connections_aiter)
        handshake_finished_1 = forker.fork(is_active=True)
        handshake_finished_2 = forker.fork(is_active=True)

        # Reads messages one at a time from the TCP connection
        messages_aiter = join_aiters(map_aiter(self.connection_to_message, handshake_finished_1, 100))

        # Handles each message one at a time, and yields responses to send back or broadcast
        responses_aiter = join_aiters(map_aiter(
            partial_func.partial_async_gen(self.handle_message, api),
            messages_aiter, 100))

        # Uses a forked aiter, and calls the on_connect function to send some initial messages
        # as soon as the connection is established
        on_connect_outbound_aiter = join_aiters(map_aiter(self.connection_to_outbound,
                                                          handshake_finished_2, 100))
        # Also uses the instance variable _outbound_aiter, which clients can use to send messages
        # at any time, not just on_connect.
        outbound_aiter_mapped = map_aiter(lambda x: (None, x), self._outbound_aiter)

        responses_aiter = join_aiters(iter_to_aiter([responses_aiter, on_connect_outbound_aiter,
                                                     outbound_aiter_mapped]))

        # For each outbound message, replicate for each peer that we need to send to
        expanded_messages_aiter = join_aiters(map_aiter(
            self.expand_outbound_messages, responses_aiter, 100))

        # This will run forever. Sends each message through the TCP connection, using the
        # length encoding and CBOR serialization
        async def serve_forever():
            async for connection, message in expanded_messages_aiter:
                log.info(f"-> {message.function} to peer {connection.get_peername()}")
                try:
                    await connection.send(message)
                except ConnectionResetError:
                    log.error(f"Cannot write to {connection}, already closed")

        # We will return a task for this, so user of start_chia_server or start_chia_client can wait until
        # the server is closed.
        return asyncio.get_running_loop().create_task(serve_forever())

    async def stream_reader_writer_to_connection(self,
                                                 swrt: Tuple[asyncio.StreamReader, asyncio.StreamWriter],
                                                 server_port: int) -> Connection:
        """
        Maps a pair of (StreamReader, StreamWriter) to a Connection object,
        which also stores the type of connection (str). It is also added to the global list.
        """
        sr, sw = swrt
        con = Connection(self._local_type, None, sr, sw, server_port)

        log.info(f"Connection with {con.get_peername()} established")
        return con

    async def connection_to_outbound(self, connection: Connection) -> AsyncGenerator[
                    Tuple[Connection, OutboundMessage], None]:
        """
        Async generator which calls the on_connect async generator method, and yields any outbound messages.
        """
        if connection.node_id in self._on_connect_callbacks:
            on_connect = self._on_connect_callbacks[connection.node_id]
            async for outbound_message in on_connect():
                yield connection, outbound_message
        if self._on_connect_generic_callback:
            async for outbound_message in self._on_connect_generic_callback():
                yield connection, outbound_message

    async def perform_handshake(self, connection: Connection) -> AsyncGenerator[Connection, None]:
        """
        Performs handshake with this new connection, and yields the connection. If the handshake
        is unsuccessful, or we already have a connection with this peer, the connection is closed,
        and nothing is yielded.
        """
        # Send handshake message
        node_id: bytes32 = create_node_id(connection.local_host, connection.local_port, connection.local_type)
        outbound_handshake = Message("handshake", Handshake(protocol_version, node_id, self._local_type))

        try:
            await connection.send(outbound_handshake)

            # Read handshake message
            full_message = await connection.read_one_message()
            inbound_handshake = Handshake(**full_message.data)
            if full_message.function != "handshake" or not inbound_handshake or not inbound_handshake.node_type:
                raise InvalidHandshake("Invalid handshake")

            # Makes sure that we only start one connection with each peer
            connection.node_id = inbound_handshake.node_id
            connection.connection_type = inbound_handshake.node_type
            if self.global_connections.have_connection(connection):
                log.warning(f"Duplicate connection to {connection}")
                return

            self.global_connections.add(connection)

            # Send Ack message
            await connection.send(Message("handshake_ack", HandshakeAck()))

            # Read Ack message
            full_message = await connection.read_one_message()
            if full_message.function != "handshake_ack":
                raise InvalidAck("Invalid ack")

            if inbound_handshake.version != protocol_version:
                raise IncompatibleProtocolVersion(f"Our node version {protocol_version} is not compatible with peer\
                        {connection} version {inbound_handshake.version}")

            log.info((f"Handshake with {NodeType(connection.connection_type).name} {connection.get_peername()} "
                      f"{connection.node_id}"
                      f" established"))
            # Only yield a connection if the handshake is succesful and the connection is not a duplicate.
            yield connection
        except (IncompatibleProtocolVersion, InvalidAck,
                InvalidHandshake, asyncio.IncompleteReadError, ConnectionResetError) as e:
            log.warning(f"{e}, handshake not completed. Connection not created.")
            connection.close()

    async def connection_to_message(self, connection: Connection) -> AsyncGenerator[
                    Tuple[Connection, Message], None]:
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
            log.warning(f"Received EOF from {connection.get_peername()}, closing connection.")
        except ConnectionError:
            log.warning(f"Connection error by peer {connection.get_peername()}, closing connection.")
        finally:
            # Removes the connection from the global list, so we don't try to send things to it
            self.global_connections.close(connection)

    async def handle_message(self, pair: Tuple[Connection, Message], api: Any) -> AsyncGenerator[
            Tuple[Connection, OutboundMessage], None]:
        """
        Async generator which takes messages, parses, them, executes the right
        api function, and yields responses (to same connection, propagated, etc).
        """
        connection, full_message = pair
        try:
            f = getattr(api, full_message.function)
            if f is not None:
                log.info(f"<- {f.__name__} from peer {connection.get_peername()}")
                result = f(full_message.data)
                if isinstance(result, AsyncGenerator):
                    async for outbound_message in result:
                        yield connection, outbound_message
                else:
                    await result
            else:
                log.error(f'Invalid message: {full_message.function} from {connection.get_peername()}')
        except Exception as e:
            log.error(f"Error {type(e)} {e}, closing connection {connection}")
            self.global_connections.close(connection)

    async def expand_outbound_messages(self, pair: Tuple[Connection, OutboundMessage]) -> AsyncGenerator[
            Tuple[Connection, Message], None]:
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
            typed_peers: List[Connection] = [peer for peer in self.global_connections.get_connections()
                                             if peer.connection_type == outbound_message.peer_type]
            if len(typed_peers) == 0:
                return
            yield (random.choice(typed_peers), outbound_message.message)
        elif (outbound_message.delivery_method == Delivery.BROADCAST or
              outbound_message.delivery_method == Delivery.BROADCAST_TO_OTHERS):
            # Broadcast to all peers.
            for peer in self.global_connections.get_connections():
                if peer.connection_type == outbound_message.peer_type:
                    if peer == connection:
                        if outbound_message.delivery_method == Delivery.BROADCAST:
                            yield (peer, outbound_message.message)
                    else:
                        yield (peer, outbound_message.message)
