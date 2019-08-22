import logging
import asyncio
from typing import Tuple, AsyncGenerator
from types import ModuleType, GeneratorType
from src.util import cbor
from lib.aiter.aiter.server import start_server_aiter
from lib.aiter.aiter import parallel_map_aiter, map_aiter, join_aiters, iter_to_aiter
from lib.aiter.aiter.push_aiter import push_aiter
from src.server.connection import Connection, PeerConnections
from src.server.outbound_message import OutboundMessage

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 5
TOTAL_RETRY_SECONDS: int = 20
RETRY_INTERVAL: int = 5

log = logging.getLogger(__name__)
global_connections: PeerConnections = PeerConnections([])


async def stream_reader_writer_to_connection(connection_type: str,
                                             pair: Tuple[asyncio.StreamReader, asyncio.StreamWriter]) -> Connection:
    """
    Maps a pair of (StreamReader, StreamWriter) to a Connection object,
    which also stores the type of connection (str). It is also added to the global list.
    """
    sr, sw = pair
    con = Connection(connection_type, sr, sw)

    await global_connections.add(con)

    log.info(f"Connection with {connection_type} {con.get_peername()} established")
    return con


async def connection_to_message(connection: Connection) -> AsyncGenerator[Tuple[Connection, bytes], None]:
    """
    Async generator which yields complete binary messages from connections,
    along with a streamwriter to send back responses. On EOF received, the connection
    is removed from the global list.
    """

    try:
        while not connection.reader.at_eof():
            size = await connection.reader.readexactly(LENGTH_BYTES)
            full_message_length = int.from_bytes(size, "big")
            full_message = await connection.reader.readexactly(full_message_length)
            yield (connection, full_message)
    except asyncio.IncompleteReadError:
        log.warn(f"Received EOF from {connection.get_peername()}, closing connection.")
    finally:
        # Removes the connection from the global list, so we don't try to send things to it
        await global_connections.remove(connection)
        connection.writer.close()


async def handle_message(api: ModuleType, pair: Tuple[Connection, bytes]) -> AsyncGenerator[
        Tuple[Connection, OutboundMessage], None]:
    """
    Async generator which takes messages, parses, them, executes the right
    api function, and yields responses (to same connection, propagated, etc).
    """
    connection, message = pair
    decoded = cbor.loads(message)
    function: str = decoded["function"]
    function_data: bytes = decoded["data"]
    f = getattr(api, function)
    if f is not None:
        if isinstance(f, GeneratorType):
            async for outbound_message in f(function_data):
                yield connection, outbound_message
        else:
            await f(function_data)
    else:
        log.error(f'Invalid message: {function} from {connection.get_peername()}')


async def expand_outbound_messages(pair: Tuple[Connection, OutboundMessage]) -> AsyncGenerator[
        Tuple[Connection, OutboundMessage], None]:
    """
    Expands each of the outbound messages into it's own message.
    """
    connection, outbound_message = pair
    if connection and not outbound_message.broadcast:
        if outbound_message.respond:
            yield connection, outbound_message
    else:
        to_yield = []
        async with global_connections.get_lock():
            for peer in await global_connections.get_connections():
                if peer.connection_type == outbound_message.peer_type:
                    if peer == connection:
                        if outbound_message.respond:
                            to_yield.append((peer, outbound_message))
                    else:
                        to_yield.append((peer, outbound_message))
        for item in to_yield:
            yield item


async def serve_forever(aiter: AsyncGenerator[Tuple[asyncio.StreamReader, asyncio.StreamWriter], None],
                        api: ModuleType, connection_type: str,
                        outbound_aiter: AsyncGenerator[OutboundMessage, None]) -> None:
    def partial_async_gen(f, first_param):
        async def inner(second_param):
            async for x in f(first_param, second_param):
                yield x
        return inner

    def partial_async(f, first_param):
        async def inner(second_param):
            return await f(first_param, second_param)
        return inner

    # Maps a stream reader and writer to connection object
    connections_aiter = map_aiter(partial_async(stream_reader_writer_to_connection, connection_type),
                                  aiter)

    # Reads messages one at a time from the TCP connection
    messages_aiter = join_aiters(parallel_map_aiter(connection_to_message, 100, connections_aiter))

    # Handles each message one at a time, and yields responses to send back or broadcast
    responses_aiter = join_aiters(parallel_map_aiter(
        partial_async_gen(handle_message, api),
        100, messages_aiter))

    if outbound_aiter is not None:
        # Includes messages sent using the argument outbound_aiter, which are not triggered by
        # network messages, but rather the node itself. (i.e: initialization, timer, etc).
        outbound_aiter_mapped = map_aiter(lambda x: (None, x), outbound_aiter)
        outbound_messages_aiter = join_aiters(iter_to_aiter([responses_aiter, outbound_aiter_mapped]))
    else:
        outbound_messages_aiter = responses_aiter

    # For each outbound message, replicate for each peer that we need to send to
    expanded_messages_aiter = join_aiters(parallel_map_aiter(
        expand_outbound_messages, 100, outbound_messages_aiter))

    # This will run forever. Sends each message through the TCP connection, using the
    # length encoding and CBOR serialization
    async for connection, message in expanded_messages_aiter:
        log.info(f"Sending {message.function} to peer {connection.get_peername()}")
        encoded: bytes = cbor.dumps({"function": message.function, "data": message.data})
        assert(len(encoded) < (2**(LENGTH_BYTES*8)))
        connection.writer.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
        await connection.writer.drain()


async def start_chia_server(host: str, port: int, api: ModuleType, connection_type: str) -> Tuple[
        asyncio.Task, push_aiter]:
    """
    Starts a server in the corresponding host and port, which serves the API provided. The connection
    specifies the type of clients that the server will talk to. Returns a task that will run forever,
    as well as a push_aiter that can be used to send messages to clients.
    Client connections are stored in the global_connections object as they are created.
    """
    outbound_aiter = push_aiter()
    _, aiter = await start_server_aiter(port, host=host)
    log.info(f"Server started at {host}:{port}")
    return (asyncio.create_task(serve_forever(aiter, api, connection_type, outbound_aiter)),
            outbound_aiter)


async def start_chia_client(target_host: str, target_port: int, api: ModuleType, connection_type: str) -> Tuple[
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
            reader, writer = await asyncio.open_connection(target_host, target_port)
            aiter = push_aiter()
            aiter.push((reader, writer))
            return (asyncio.create_task(serve_forever(aiter, api, connection_type, outbound_aiter)),
                    outbound_aiter)
        except ConnectionRefusedError:
            print(f"Connection to {target_host}:{target_port} refused.")
            await asyncio.sleep(RETRY_INTERVAL)
        total_time += RETRY_INTERVAL
    raise TimeoutError(f"Failed to connect to {connection_type} at {target_host}:{target_port}")
