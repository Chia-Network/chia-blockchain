import logging
import asyncio
import random
from typing import Tuple, AsyncGenerator, Callable, Optional, List, Any
from lib.aiter.aiter.server import start_server_aiter
from lib.aiter.aiter.map_aiter import map_aiter
from lib.aiter.aiter.join_aiters import join_aiters
from lib.aiter.aiter.parallel_map_aiter import parallel_map_aiter
from lib.aiter.aiter.iter_to_aiter import iter_to_aiter
from lib.aiter.aiter.aiter_forker import aiter_forker
from lib.aiter.aiter.push_aiter import push_aiter
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.server.connection import Connection, PeerConnections
from src.server.outbound_message import OutboundMessage, Delivery, Message, NodeType
from src.protocols.shared_protocol import Handshake, HandshakeAck, protocol_version
from src.util import partial_func
from src.util.errors import InvalidHandshake, IncompatibleProtocolVersion, DuplicateConnection
from src.util.network import create_node_id

exited = False
# Each message is prepended with LENGTH_BYTES bytes specifying the length
TOTAL_RETRY_SECONDS: int = 10
RETRY_INTERVAL: int = 2

log = logging.getLogger(__name__)

# Global object that stores all connections
global_connections: PeerConnections = PeerConnections([])


async def stream_reader_writer_to_connection(pair: Tuple[asyncio.StreamReader, asyncio.StreamWriter],
                                             connection_type: NodeType, server_port: int) -> Connection:
    """
    Maps a pair of (StreamReader, StreamWriter) to a Connection object,
    which also stores the type of connection (str). It is also added to the global list.
    """
    sr, sw = pair
    con = Connection(connection_type, sr, sw, server_port)

    await global_connections.add(con)

    log.info(f"Connection with {connection_type} {con.get_peername()} established")
    return con


async def connection_to_outbound(connection: Connection,
                                 on_connect: Callable[[], AsyncGenerator[OutboundMessage, None]]) -> AsyncGenerator[
            Tuple[Connection, OutboundMessage], None]:
    """
    Async generator which calls the on_connect async generator method, and yields any outbound messages.
    """
    async for outbound_message in on_connect():
        yield connection, outbound_message


async def perform_handshake(connection: Connection) -> AsyncGenerator[Optional[Connection], None]:
    """
    Performs handshake with this new connection, and yields the connection. If the handshake
    is unsuccessful, or we already have a connection with this peer, the connection is closed,
    and nothing is yielded.
    """

    # Send handshake message
    node_id: bytes32 = create_node_id(connection)
    outbound_handshake = Message("handshake", Handshake(protocol_version, node_id))
    await connection.send(outbound_handshake)

    try:
        # Read handshake message
        full_message = await connection.read_one_message()
        inbound_handshake = full_message.data
        if full_message.function != "handshake" or not inbound_handshake:
            raise InvalidHandshake()
        # Send Ack message
        await connection.send(Message("handshake_ack", HandshakeAck()))

        # Read Ack message
        full_message = await connection.read_one_message()
        if full_message.function != "handshake_ack":
            raise InvalidHandshake()
        if inbound_handshake.version != protocol_version:
            raise IncompatibleProtocolVersion(f"Our node version {protocol_version} is not compatible with peer\
                    {connection} version {inbound_handshake.version}")
        if await global_connections.already_have_connection(inbound_handshake.node_id):
            connection.node_id = inbound_handshake.node_id
            raise DuplicateConnection(f"Already have connection to {connection}")
        connection.node_id = inbound_handshake.node_id
        log.info((f"Handshake with {connection.connection_type} {connection.get_peername()} {connection.node_id}"
                  f" established"))
        # Only yield a connection if the handshake is succesful and the connection is not a duplicate.
        yield connection

    except (IncompatibleProtocolVersion, InvalidHandshake, DuplicateConnection, asyncio.IncompleteReadError) as e:
        log.warning(f"{e}")
        await global_connections.close(connection)
        yield None


async def connection_to_message(connection: Optional[Connection]) -> AsyncGenerator[Tuple[Connection, Message], None]:
    """
    Async generator which yields complete binary messages from connections,
    along with a streamwriter to send back responses. On EOF received, the connection
    is removed from the global list.
    """
    if connection is not None:
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
            await global_connections.close(connection)


async def handle_message(pair: Tuple[Connection, Message], api: Any) -> AsyncGenerator[
        Tuple[Connection, OutboundMessage], None]:
    """
    Async generator which takes messages, parses, them, executes the right
    api function, and yields responses (to same connection, propagated, etc).
    """
    connection, full_message = pair
    try:
        f = getattr(api, full_message.function)
        if f is not None:
            result = f(full_message.data)
            if isinstance(result, AsyncGenerator):
                async for outbound_message in result:
                    yield connection, outbound_message
            else:
                await result
        else:
            log.error(f'Invalid message: {full_message.function} from {connection.get_peername()}')
    except Exception as e:
        log.error(f"Error {e}, closing connection {connection}")
        await global_connections.close(connection)


async def expand_outbound_messages(pair: Tuple[Connection, OutboundMessage]) -> AsyncGenerator[
        Tuple[Connection, Message], None]:
    """
    Expands each of the outbound messages into it's own message.
    """
    connection, outbound_message = pair

    if connection and outbound_message.delivery_method == Delivery.RESPOND:
        # Only select this peer.
        yield connection, outbound_message.message
    elif outbound_message.delivery_method == Delivery.RANDOM:
        # Select a random peer.
        to_yield_single: Tuple[Connection, Message]
        async with global_connections.get_lock():
            typed_peers: List[Connection] = [peer for peer in await global_connections.get_connections()
                                             if peer.connection_type == outbound_message.peer_type]
            if len(typed_peers) == 0:
                return
            to_yield_single = (random.choice(typed_peers), outbound_message.message)
        yield to_yield_single
    elif (outbound_message.delivery_method == Delivery.BROADCAST or
          outbound_message.delivery_method == Delivery.BROADCAST_TO_OTHERS):
        # Broadcast to all peers.
        to_yield: List[Tuple[Connection, Message]] = []
        async with global_connections.get_lock():
            for peer in await global_connections.get_connections():
                if peer.connection_type == outbound_message.peer_type:
                    if peer == connection:
                        if outbound_message.delivery_method == Delivery.BROADCAST:
                            to_yield.append((peer, outbound_message.message))
                    else:
                        to_yield.append((peer, outbound_message.message))
        for item in to_yield:
            yield item


async def initialize_pipeline(aiter,
                              api: Any, server_port: int, connection_type: NodeType,
                              on_connect: Callable[[], AsyncGenerator[OutboundMessage, None]] = None,
                              outbound_aiter=None,
                              wait_for_handshake=False) -> asyncio.Task:

    # Maps a stream reader and writer to connection object
    connections_aiter = map_aiter(partial_func.partial_async(stream_reader_writer_to_connection,
                                                             connection_type, server_port), aiter)
    # Performs a handshake with the peer
    handshaked_connections_aiter = join_aiters(map_aiter(perform_handshake, connections_aiter))
    forker = aiter_forker(handshaked_connections_aiter)
    handshake_finished_1 = forker.fork(is_active=True)
    handshake_finished_2 = forker.fork(is_active=True)
    handshake_finished_3 = forker.fork(is_active=True)

    # Reads messages one at a time from the TCP connection
    messages_aiter = join_aiters(parallel_map_aiter(connection_to_message, handshake_finished_1, 100))

    # Handles each message one at a time, and yields responses to send back or broadcast
    responses_aiter = join_aiters(parallel_map_aiter(
        partial_func.partial_async_gen(handle_message, api),
        messages_aiter, 100))

    if on_connect is not None:
        # Uses a forked aiter, and calls the on_connect function to send some initial messages
        # as soon as the connection is established

        on_connect_outbound_aiter = join_aiters(parallel_map_aiter(
            partial_func.partial_async_gen(connection_to_outbound, on_connect), handshake_finished_2, 100))

        responses_aiter = join_aiters(iter_to_aiter([responses_aiter, on_connect_outbound_aiter]))
    if outbound_aiter is not None:
        # Includes messages sent using the argument outbound_aiter, which are not triggered by
        # network messages, but rather the node itself. (i.e: initialization, timer, etc).
        outbound_aiter_mapped = map_aiter(lambda x: (None, x), outbound_aiter)
        responses_aiter = join_aiters(iter_to_aiter([responses_aiter, outbound_aiter_mapped]))

    # For each outbound message, replicate for each peer that we need to send to
    expanded_messages_aiter = join_aiters(parallel_map_aiter(
        expand_outbound_messages, responses_aiter, 100))

    # This will run forever. Sends each message through the TCP connection, using the
    # length encoding and CBOR serialization
    async def serve_forever():
        try:
            async for connection, message in expanded_messages_aiter:
                log.info(f"-> {message.function} to peer {connection.get_peername()}")
                try:
                    await connection.send(message)
                except ConnectionResetError:
                    log.error(f"Cannot write to {connection}, already closed")
        except asyncio.CancelledError:
            await global_connections.close_all_connections()
            raise

    # We will return a task for this, so user of start_chia_server or start_chia_client can wait until
    # the server is closed.
    ret_task = asyncio.create_task(serve_forever())

    if wait_for_handshake:
        # Waits for the handshake with the first connection
        async for _ in handshake_finished_3:
            break

    return ret_task


async def start_chia_server(host: str, port: int, api: Any, connection_type: NodeType,
                            on_connect: Optional[Callable[[], AsyncGenerator[OutboundMessage, None]]] = None) -> Tuple[
        asyncio.Task, push_aiter]:
    """
    Starts a server in the corresponding host and port, which serves the API provided. The connection
    specifies the type of clients that the server will talk to. Returns a task that will run forever,
    as well as a push_aiter that can be used to send messages to clients.
    Client connections are stored in the global_connections object as they are created.
    """
    outbound_aiter = push_aiter()

    _, aiter = await start_server_aiter(port, host=host, reuse_address=True)
    log.info(f"Server started at {host}:{port}")
    return (await initialize_pipeline(aiter, api, port, connection_type, on_connect, outbound_aiter, False),
            outbound_aiter)


async def start_chia_client(target_node: PeerInfo,
                            server_port: int,
                            api: Any, connection_type: NodeType) -> Tuple[
        asyncio.Task, push_aiter]:
    """
    Initiates a connection to the corresponding host and port, which serves the API provided. The connection
    specifies the type of clients that the server will talk to. Returns a task that will run forever,
    as well as a push_aiter that can be used to send messages to server. Performs several retries
    if connection fails.
    The server connection is stored in the global_connections object after it is created.
    """
    outbound_aiter = push_aiter()

    total_time: int = 0
    for _ in range(0, TOTAL_RETRY_SECONDS, RETRY_INTERVAL):
        try:
            async with global_connections.get_lock():
                if any(((c.peer_host == target_node.host and c.peer_port == target_node.port)
                        or (c.node_id == target_node.node_id))
                        for c in await global_connections.get_connections()):
                    raise RuntimeError("Already have connection to {target_host}")
            reader, writer = await asyncio.open_connection(target_node.host, target_node.port)
            aiter = push_aiter()
            aiter.push((reader, writer))
            return (await initialize_pipeline(aiter, api, server_port, connection_type, None, outbound_aiter, True),
                    outbound_aiter)
        except ConnectionRefusedError:
            log.warning(f"Connection to {target_node.host}:{target_node.port} refused.")
            await asyncio.sleep(RETRY_INTERVAL)
        total_time += RETRY_INTERVAL
    raise asyncio.CancelledError(f"Failed to connect to {connection_type} at {target_node.host}:{target_node.port}")
