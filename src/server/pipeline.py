import asyncio
import concurrent
import logging
import random
import ssl
from typing import Any, AsyncGenerator, List, Optional, Tuple

from aiter import aiter_forker, iter_to_aiter, join_aiters, map_aiter, push_aiter

from src.protocols.shared_protocol import (
    Handshake,
    HandshakeAck,
    Ping,
    Pong,
    protocol_version,
)
from src.server.connection import Connection, OnConnectFunc, PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.sized_bytes import bytes32
from src.util import partial_func
from src.util.errors import Err, ProtocolError
from src.util.ints import uint16
import traceback


async def initialize_pipeline(
    aiter,
    api: Any,
    server_port: int,
    outbound_aiter: push_aiter,
    global_connections: PeerConnections,
    local_type: NodeType,
    node_id: bytes32,
    network_id: bytes32,
    log: logging.Logger,
):
    """
    A pipeline that starts with (StreamReader, StreamWriter), maps it though to
    connections, messages, executes a local API call, and returns responses.
    """
    srwt_aiter = aiter

    # Maps a stream reader, writer and NodeType to a Connection object
    connections_aiter = map_aiter(
        partial_func.partial_async(
            stream_reader_writer_to_connection, server_port, local_type, log,
        ),
        aiter,
    )

    def add_global_connections(connection):
        return connection, global_connections

    connections_with_global_connections_aiter = map_aiter(
        add_global_connections, connections_aiter
    )

    # Performs a handshake with the peer

    outbound_handshake = Message(
        "handshake",
        Handshake(
            network_id, protocol_version, node_id, uint16(server_port), local_type,
        ),
    )

    handshaked_connections_aiter = join_aiters(
        map_aiter(
            lambda _: perform_handshake(_, srwt_aiter, outbound_handshake),
            connections_with_global_connections_aiter,
        )
    )
    forker = aiter_forker(handshaked_connections_aiter)
    handshake_finished_1 = forker.fork(is_active=True)
    handshake_finished_2 = forker.fork(is_active=True)

    # Reads messages one at a time from the TCP connection
    messages_aiter = join_aiters(
        map_aiter(connection_to_message, handshake_finished_1, 100)
    )

    # Handles each message one at a time, and yields responses to send back or broadcast
    responses_aiter = join_aiters(
        map_aiter(
            partial_func.partial_async_gen(handle_message, api), messages_aiter, 100,
        )
    )

    # Uses a forked aiter, and calls the on_connect function to send some initial messages
    # as soon as the connection is established
    on_connect_outbound_aiter = join_aiters(
        map_aiter(connection_to_outbound, handshake_finished_2, 100)
    )

    # Also uses the instance variable _outbound_aiter, which clients can use to send messages
    # at any time, not just on_connect.
    outbound_aiter_mapped = map_aiter(
        lambda x: (None, x, global_connections), outbound_aiter
    )

    responses_aiter = join_aiters(
        iter_to_aiter(
            [responses_aiter, on_connect_outbound_aiter, outbound_aiter_mapped]
        )
    )

    # For each outbound message, replicate for each peer that we need to send to
    expanded_messages_aiter = join_aiters(
        map_aiter(expand_outbound_messages, responses_aiter, 100)
    )

    # This will run forever. Sends each message through the TCP connection, using the
    # length encoding and CBOR serialization
    async for connection, message in expanded_messages_aiter:
        if message is None:
            # Does not ban the peer, this is just a graceful close of connection.
            global_connections.close(connection, True)
            continue
        if connection.is_closing():
            connection.log.info(
                f"Closing, so will not send {message.function} to peer {connection.get_peername()}"
            )
            continue
        connection.log.info(
            f"-> {message.function} to peer {connection.get_peername()}"
        )
        try:
            await connection.send(message)
        except (RuntimeError, TimeoutError, OSError,) as e:
            connection.log.warning(
                f"Cannot write to {connection}, already closed. Error {e}."
            )
            global_connections.close(connection, True)


async def stream_reader_writer_to_connection(
    swrt: Tuple[asyncio.StreamReader, asyncio.StreamWriter, OnConnectFunc],
    server_port: int,
    local_type: NodeType,
    log: logging.Logger,
) -> Connection:
    """
    Maps a tuple of (StreamReader, StreamWriter, on_connect) to a Connection object,
    which also stores the type of connection (str). It is also added to the global list.
    """
    sr, sw, on_connect = swrt
    con = Connection(local_type, None, sr, sw, server_port, on_connect, log)

    con.log.info(f"Connection with {con.get_peername()} established")
    return con


async def connection_to_outbound(
    pair: Tuple[Connection, PeerConnections],
) -> AsyncGenerator[Tuple[Connection, OutboundMessage, PeerConnections], None]:
    """
    Async generator which calls the on_connect async generator method, and yields any outbound messages.
    """
    connection, global_connections = pair
    if connection.on_connect:
        async for outbound_message in connection.on_connect():
            yield connection, outbound_message, global_connections


async def perform_handshake(
    pair: Tuple[Connection, PeerConnections],
    srwt_aiter: push_aiter,
    outbound_handshake: Message,
) -> AsyncGenerator[Tuple[Connection, PeerConnections], None]:
    """
    Performs handshake with this new connection, and yields the connection. If the handshake
    is unsuccessful, or we already have a connection with this peer, the connection is closed,
    and nothing is yielded.
    """
    connection, global_connections = pair

    # Send handshake message
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
            raise ProtocolError(Err.INVALID_HANDSHAKE)

        if inbound_handshake.node_id == outbound_handshake.data.node_id:
            raise ProtocolError(Err.SELF_CONNECTION)

        # Makes sure that we only start one connection with each peer
        connection.node_id = inbound_handshake.node_id
        connection.peer_server_port = int(inbound_handshake.server_port)
        connection.connection_type = inbound_handshake.node_type

        if srwt_aiter.is_stopped():
            raise Exception("No longer accepting handshakes, closing.")

        if not global_connections.add(connection):
            raise ProtocolError(Err.DUPLICATE_CONNECTION, [False])

        # Send Ack message
        await connection.send(Message("handshake_ack", HandshakeAck()))

        # Read Ack message
        full_message = await connection.read_one_message()
        if full_message.function != "handshake_ack":
            raise ProtocolError(Err.INVALID_ACK)

        if inbound_handshake.version != protocol_version:
            raise ProtocolError(
                Err.INCOMPATIBLE_PROTOCOL_VERSION,
                [protocol_version, inbound_handshake.version],
            )

        connection.log.info(
            (
                f"Handshake with {NodeType(connection.connection_type).name} {connection.get_peername()} "
                f"{connection.node_id}"
                f" established"
            )
        )
        # Only yield a connection if the handshake is succesful and the connection is not a duplicate.
        yield connection, global_connections
    except (ProtocolError, asyncio.IncompleteReadError, OSError, Exception,) as e:
        connection.log.warning(f"{e}, handshake not completed. Connection not created.")
        # Make sure to close the connection even if it's not in global connections
        connection.close()
        # Remove the conenction from global connections
        global_connections.close(connection)


async def connection_to_message(
    pair: Tuple[Connection, PeerConnections],
) -> AsyncGenerator[Tuple[Connection, Message, PeerConnections], None]:
    """
    Async generator which yields complete binary messages from connections,
    along with a streamwriter to send back responses. On EOF received, the connection
    is removed from the global list.
    """
    connection, global_connections = pair

    try:
        while not connection.reader.at_eof():
            message = await connection.read_one_message()
            # Read one message at a time, forever
            yield (connection, message, global_connections)
    except asyncio.IncompleteReadError:
        connection.log.info(
            f"Received EOF from {connection.get_peername()}, closing connection."
        )
    except ConnectionError:
        connection.log.warning(
            f"Connection error by peer {connection.get_peername()}, closing connection."
        )
    except AttributeError as e:
        connection.log.warning(
            f"AttributeError {e} in connection with peer {connection.get_peername()}."
        )
    except ssl.SSLError as e:
        connection.log.warning(
            f"SSLError {e} in connection with peer {connection.get_peername()}."
        )
    except (
        concurrent.futures._base.CancelledError,
        OSError,
        TimeoutError,
        asyncio.TimeoutError,
    ) as e:
        tb = traceback.format_exc()
        connection.log.error(tb)
        connection.log.error(
            f"Timeout/OSError {e} in connection with peer {connection.get_peername()}, closing connection."
        )
    finally:
        # Removes the connection from the global list, so we don't try to send things to it
        global_connections.close(connection, True)


async def handle_message(
    triple: Tuple[Connection, Message, PeerConnections], api: Any
) -> AsyncGenerator[Tuple[Connection, OutboundMessage, PeerConnections], None]:
    """
    Async generator which takes messages, parses, them, executes the right
    api function, and yields responses (to same connection, propagated, etc).
    """
    connection, full_message, global_connections = triple

    try:
        if len(full_message.function) == 0 or full_message.function.startswith("_"):
            # This prevents remote calling of private methods that start with "_"
            raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [full_message.function])

        connection.log.info(
            f"<- {full_message.function} from peer {connection.get_peername()}"
        )
        if full_message.function == "ping":
            ping_msg = Ping(full_message.data["nonce"])
            assert connection.connection_type
            outbound_message = OutboundMessage(
                connection.connection_type,
                Message("pong", Pong(ping_msg.nonce)),
                Delivery.RESPOND,
            )
            yield connection, outbound_message, global_connections
            return
        elif full_message.function == "pong":
            return

        f_with_peer_name = getattr(api, full_message.function + "_with_peer_name", None)

        if f_with_peer_name is not None:
            result = f_with_peer_name(full_message.data, connection.get_peername())
        else:
            f = getattr(api, full_message.function, None)

            if f is None:
                raise ProtocolError(
                    Err.INVALID_PROTOCOL_MESSAGE, [full_message.function]
                )

            result = f(full_message.data)

        if isinstance(result, AsyncGenerator):
            async for outbound_message in result:
                yield connection, outbound_message, global_connections
        else:
            await result
    except Exception:
        tb = traceback.format_exc()
        connection.log.error(f"Error, closing connection {connection}. {tb}")
        # TODO: Exception means peer gave us invalid information, so ban this peer.
        global_connections.close(connection)


async def expand_outbound_messages(
    triple: Tuple[Connection, OutboundMessage, PeerConnections]
) -> AsyncGenerator[Tuple[Connection, Optional[Message]], None]:
    """
    Expands each of the outbound messages into it's own message.
    """

    connection, outbound_message, global_connections = triple

    if connection and outbound_message.delivery_method == Delivery.RESPOND:
        if connection.connection_type == outbound_message.peer_type:
            # Only select this peer, and only if it's the right type
            yield connection, outbound_message.message
    elif outbound_message.delivery_method == Delivery.RANDOM:
        # Select a random peer.
        to_yield_single: Tuple[Connection, Message]
        typed_peers: List[Connection] = [
            peer
            for peer in global_connections.get_connections()
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
        for peer in global_connections.get_connections():
            if peer.connection_type == outbound_message.peer_type:
                if peer == connection:
                    if outbound_message.delivery_method == Delivery.BROADCAST:
                        yield (peer, outbound_message.message)
                else:
                    yield (peer, outbound_message.message)

    elif outbound_message.delivery_method == Delivery.SPECIFIC:
        # Send to a specific peer, by node_id, assuming the NodeType matches.
        if outbound_message.specific_peer_node_id is None:
            return
        for peer in global_connections.get_connections():
            if (
                peer.connection_type == outbound_message.peer_type
                and peer.node_id == outbound_message.specific_peer_node_id
            ):
                yield (peer, outbound_message.message)

    elif outbound_message.delivery_method == Delivery.CLOSE:
        if outbound_message.specific_peer_node_id is None:
            # Close the connection but don't ban the peer
            if connection.connection_type == outbound_message.peer_type:
                yield (connection, None)
        else:
            for peer in global_connections.get_connections():
                # Close the connection with the specific peer
                if (
                    peer.connection_type == outbound_message.peer_type
                    and peer.node_id == outbound_message.specific_peer_node_id
                ):
                    yield (peer, outbound_message.message)
