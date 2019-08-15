import logging
import asyncio
import functools
from src.util import cbor
from lib.aiter.aiter.server import start_server_aiter
from lib.aiter import parallel_map_aiter, map_aiter, join_aiters
from src.server.connection import Connection
from src.server.peer_connections import PeerConnections

# Each message is prepended with LENGTH_BYTES bytes specifying the length
LENGTH_BYTES: int = 5
log = logging.getLogger(__name__)
global_connections: PeerConnections = PeerConnections([])


async def stream_reader_writer_to_connection(connection_type, pair):
    sr, sw = pair
    return Connection(connection_type, sr, sw)


async def connection_to_message(connection):
    """
    Async generator which yields complete binary messages from connections,
    along with a streamwriter to send back responses.
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
        with await global_connections.get_lock():
            await global_connections.remove(connection)
        connection.writer.close()
        return


async def handle_message(api, pair):
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
        async for outbound_message in f(function_data):
            yield connection, outbound_message
    else:
        log.error(f'Invalid message: {function} from {connection.get_peername()}')


async def expand_outbound_messages(pair):
    """
    Expands each of the outbound messages into it's own message.
    """
    connection, outbound_message = pair
    if not outbound_message.broadcast:
        if outbound_message.respond:
            yield connection, outbound_message
    else:
        with await global_connections.get_lock():
            for peer in await global_connections.get_connections():
                if peer.connection_type == outbound_message.peer_type:
                    if peer == connection:
                        if outbound_message.respond:
                            yield connection, outbound_message
                    else:
                        yield connection, outbound_message


async def start_chia_server(host, port, api, connection_type):
    server, aiter = await start_server_aiter(port, host=host)
    connections_aiter = map_aiter(
        functools.partial(stream_reader_writer_to_connection, connection_type),
        aiter)
    messages_aiter = join_aiters(parallel_map_aiter(connection_to_message, 100, connections_aiter))
    responses_aiter = join_aiters(parallel_map_aiter(
        functools.partial(handle_message, api),
        100, messages_aiter))

    outbound_messages_aiter = join_aiters(parallel_map_aiter(
        expand_outbound_messages, 100, responses_aiter))

    async for connection, outbound_message in outbound_messages_aiter:
        log.info(f"Sending {outbound_message.function} to peer {connection.get_peername()}")
        encoded: bytes = cbor.dumps({"function": outbound_message.function, "data": outbound_message.data})
        assert(len(encoded) < (2**(LENGTH_BYTES*8)))
        connection.writer.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
        await connection.writer.drain()
