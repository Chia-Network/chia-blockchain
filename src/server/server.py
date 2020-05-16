import asyncio
import concurrent
import logging
from pathlib import Path
import random
import ssl
from secrets import token_bytes
from typing import Any, AsyncGenerator, List, Optional, Tuple, Dict

from aiter import aiter_forker, iter_to_aiter, join_aiters, map_aiter, push_aiter
from aiter.server import start_server_aiter

from src.protocols.shared_protocol import (
    Handshake,
    HandshakeAck,
    Ping,
    Pong,
    protocol_version,
)
from src.server.connection import Connection, OnConnectFunc, PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util import partial_func
from src.util.config import config_path_for_filename
from src.util.errors import Err, ProtocolError
from src.util.ints import uint16
from src.util.network import create_node_id
import traceback


class ChiaServer:
    def __init__(
        self,
        port: int,
        api: Any,
        local_type: NodeType,
        ping_interval: int,
        network_id: str,
        root_path: Path,
        config: Dict,
        name: str = None,
    ):
        # Keeps track of all connections to and from this node.
        self.global_connections: PeerConnections = PeerConnections([])

        # Optional listening server. You can also use this class without starting one.
        self._server: Optional[asyncio.AbstractServer] = None

        self._port = port  # TCP port to identify our node
        self._api = api  # API module that will be called from the requests
        self._local_type = local_type  # NodeType (farmer, full node, timelord, pool, harvester, wallet)

        self._ping_interval = ping_interval
        self._network_id = network_id
        # (StreamReader, StreamWriter, NodeType) aiter, gets things from server and clients and
        # sends them through the pipeline
        self._srwt_aiter: push_aiter = push_aiter()

        # Aiter used to broadcase messages
        self._outbound_aiter: push_aiter = push_aiter()

        # Tasks for entire server pipeline
        self._pipeline_task: asyncio.Future = asyncio.ensure_future(
            self.initialize_pipeline(self._srwt_aiter, self._api, self._port)
        )

        # Our unique random node id that we will other peers, regenerated on launch
        self._node_id = create_node_id()

        # Taks list to keep references to tasks, so they don'y get GCd
        self._tasks: List[asyncio.Task] = [self._initialize_ping_task()]
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.root_path = root_path
        self.config = config

    def loadSSLConfig(self, tipo: str, path: Path, config: Dict):
        if config is not None:
            try:
                return (
                    config_path_for_filename(path, config[tipo]["crt"]),
                    config_path_for_filename(path, config[tipo]["key"]),
                )
            except Exception:
                pass

        return None, None

    async def start_server(self, on_connect: OnConnectFunc = None) -> bool:
        """
        Launches a listening server on host and port specified, to connect to NodeType nodes. On each
        connection, the on_connect asynchronous generator will be called, and responses will be sent.
        Whenever a new TCP connection is made, a new srwt tuple is sent through the pipeline.
        """
        if self._server is not None or self._pipeline_task.done():
            return False

        ssl_context = ssl._create_unverified_context(purpose=ssl.Purpose.CLIENT_AUTH)
        private_cert, private_key = self.loadSSLConfig(
            "ssl", self.root_path, self.config
        )
        ssl_context.load_cert_chain(certfile=private_cert, keyfile=private_key)
        ssl_context.load_verify_locations(private_cert)

        if (
            self._local_type == NodeType.FULL_NODE
            or self._local_type == NodeType.INTRODUCER
        ):
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context.verify_mode = ssl.CERT_REQUIRED

        self._server, aiter = await start_server_aiter(
            self._port, host=None, reuse_address=True, ssl=ssl_context
        )

        def add_connection_type(
            srw: Tuple[asyncio.StreamReader, asyncio.StreamWriter]
        ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter, OnConnectFunc]:
            ssl_object = srw[1].get_extra_info(name="ssl_object")
            peer_cert = ssl_object.getpeercert()
            self.log.info(f"Client authed as {peer_cert}")
            return (srw[0], srw[1], on_connect)

        srwt_aiter = map_aiter(add_connection_type, aiter)

        # Push all aiters that come from the server, into the pipeline
        self._tasks.append(asyncio.create_task(self._add_to_srwt_aiter(srwt_aiter)))

        self.log.info(f"Server started on port {self._port}")
        return True

    async def start_client(
        self,
        target_node: PeerInfo,
        on_connect: OnConnectFunc = None,
        auth: bool = False,
    ) -> bool:
        """
        Tries to connect to the target node, adding one connection into the pipeline, if successful.
        An on connect method can also be specified, and this will be saved into the instance variables.
        """
        if self._server is not None:
            if (
                target_node.host == "127.0.0.1"
                or target_node.host == "0.0.0.0"
                or target_node.host == "::1"
                or target_node.host == "0:0:0:0:0:0:0:1"
            ) and self._port == target_node.port:
                self.global_connections.peers.remove(target_node)
                return False
        if self._pipeline_task.done():
            return False

        ssl_context = ssl._create_unverified_context(purpose=ssl.Purpose.SERVER_AUTH)
        private_cert, private_key = self.loadSSLConfig(
            "ssl", self.root_path, self.config
        )

        ssl_context.load_cert_chain(certfile=private_cert, keyfile=private_key)
        if not auth:
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            ssl_context.load_verify_locations(private_cert)

        try:
            reader, writer = await asyncio.open_connection(
                target_node.host, int(target_node.port), ssl=ssl_context
            )
        except (
            ConnectionRefusedError,
            TimeoutError,
            OSError,
            asyncio.TimeoutError,
        ) as e:
            self.log.warning(
                f"Could not connect to {target_node}. {type(e)}{str(e)}. Aborting and removing peer."
            )
            self.global_connections.peers.remove(target_node)
            return False
        self._tasks.append(
            asyncio.create_task(
                self._add_to_srwt_aiter(iter_to_aiter([(reader, writer, on_connect)]))
            )
        )

        ssl_object = writer.get_extra_info(name="ssl_object")
        peer_cert = ssl_object.getpeercert()
        self.log.info(f"Server authed as {peer_cert}")

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
        if self._server is not None:
            self._server.close()
        if not self._outbound_aiter.is_stopped():
            self._outbound_aiter.stop()
        if not self._srwt_aiter.is_stopped():
            self._srwt_aiter.stop()

    def _initialize_ping_task(self):
        async def ping():
            while not self._pipeline_task.done():
                msg = Message("ping", Ping(bytes32(token_bytes(32))))
                self.push_message(
                    OutboundMessage(NodeType.FARMER, msg, Delivery.BROADCAST)
                )
                self.push_message(
                    OutboundMessage(NodeType.TIMELORD, msg, Delivery.BROADCAST)
                )
                self.push_message(
                    OutboundMessage(NodeType.FULL_NODE, msg, Delivery.BROADCAST)
                )
                self.push_message(
                    OutboundMessage(NodeType.HARVESTER, msg, Delivery.BROADCAST)
                )
                self.push_message(
                    OutboundMessage(NodeType.WALLET, msg, Delivery.BROADCAST)
                )
                await asyncio.sleep(self._ping_interval)

        return asyncio.create_task(ping())

    async def initialize_pipeline(self, aiter, api: Any, server_port: int):
        """
        A pipeline that starts with (StreamReader, StreamWriter), maps it though to
        connections, messages, executes a local API call, and returns responses.
        """
        global_connections = self.global_connections
        outbound_aiter = self._outbound_aiter
        local_type = self._local_type
        srwt_aiter = self._srwt_aiter
        assert self._port == server_port
        node_id = self._node_id
        network_id = self._network_id

        # Maps a stream reader, writer and NodeType to a Connection object
        connections_aiter = map_aiter(
            partial_func.partial_async(
                self.stream_reader_writer_to_connection, server_port, local_type,
            ),
            aiter,
        )

        def add_global_connections(connection):
            return connection, global_connections

        connections_with_global_connections_aiter = map_aiter(add_global_connections, connections_aiter)

        # Performs a handshake with the peer

        outbound_handshake = Message(
            "handshake",
            Handshake(
                network_id, protocol_version, node_id, uint16(server_port), local_type,
            ),
        )

        handshaked_connections_aiter = join_aiters(
            map_aiter(
                lambda _: self.perform_handshake(_, srwt_aiter, outbound_handshake),
                connections_with_global_connections_aiter,
            )
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
        outbound_aiter_mapped = map_aiter(lambda x: (None, x, global_connections), outbound_aiter)

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
        async for connection, message in expanded_messages_aiter:
            if message is None:
                # Does not ban the peer, this is just a graceful close of connection.
                global_connections.close(connection, True)
                continue
            if connection.is_closing():
                self.log.info(
                    f"Closing, so will not send {message.function} to peer {connection.get_peername()}"
                )
                continue
            self.log.info(f"-> {message.function} to peer {connection.get_peername()}")
            try:
                await connection.send(message)
            except (RuntimeError, TimeoutError, OSError,) as e:
                self.log.warning(
                    f"Cannot write to {connection}, already closed. Error {e}."
                )
                global_connections.close(connection, True)

    async def stream_reader_writer_to_connection(
        self,
        swrt: Tuple[asyncio.StreamReader, asyncio.StreamWriter, OnConnectFunc],
        server_port: int,
        local_type: NodeType,
    ) -> Connection:
        """
        Maps a tuple of (StreamReader, StreamWriter, on_connect) to a Connection object,
        which also stores the type of connection (str). It is also added to the global list.
        """
        assert self._local_type == local_type
        sr, sw, on_connect = swrt
        con = Connection(local_type, None, sr, sw, server_port, on_connect)

        self.log.info(f"Connection with {con.get_peername()} established")
        return con

    async def connection_to_outbound(
        self, pair: Tuple[Connection, PeerConnections],
    ) -> AsyncGenerator[Tuple[Connection, OutboundMessage, PeerConnections], None]:
        """
        Async generator which calls the on_connect async generator method, and yields any outbound messages.
        """
        connection, global_connections = pair
        if connection.on_connect:
            async for outbound_message in connection.on_connect():
                yield connection, outbound_message, global_connections

    async def perform_handshake(
        self,
        pair: Tuple[Connection, PeerConnections],
        srwt_aiter: push_aiter,
        outbound_handshake: Message,
    ) -> AsyncGenerator[Tuple[Connection, PeerConnections], None]:
        """
        Performs handshake with this new connection, and yields the connection. If the handshake
        is unsuccessful, or we already have a connection with this peer, the connection is closed,
        and nothing is yielded.
        """
        assert srwt_aiter == self._srwt_aiter

        connection, global_connections = pair
        assert global_connections == self.global_connections

        # Send handshake message
        assert outbound_handshake.data.network_id == self._network_id
        assert outbound_handshake.data.version == protocol_version
        assert outbound_handshake.data.node_id == self._node_id
        assert outbound_handshake.data.server_port == self._port
        assert outbound_handshake.data.node_type == self._local_type

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

            self.log.info(
                (
                    f"Handshake with {NodeType(connection.connection_type).name} {connection.get_peername()} "
                    f"{connection.node_id}"
                    f" established"
                )
            )
            # Only yield a connection if the handshake is succesful and the connection is not a duplicate.
            yield connection, global_connections
        except (ProtocolError, asyncio.IncompleteReadError, OSError, Exception,) as e:
            self.log.warning(f"{e}, handshake not completed. Connection not created.")
            # Make sure to close the connection even if it's not in global connections
            connection.close()
            # Remove the conenction from global connections
            global_connections.close(connection)

    async def connection_to_message(
        self, pair: Tuple[Connection, PeerConnections],
    ) -> AsyncGenerator[Tuple[Connection, Message, PeerConnections], None]:
        """
        Async generator which yields complete binary messages from connections,
        along with a streamwriter to send back responses. On EOF received, the connection
        is removed from the global list.
        """
        connection, global_connections = pair
        assert global_connections == self.global_connections

        try:
            while not connection.reader.at_eof():
                message = await connection.read_one_message()
                # Read one message at a time, forever
                yield (connection, message, global_connections)
        except asyncio.IncompleteReadError:
            self.log.info(
                f"Received EOF from {connection.get_peername()}, closing connection."
            )
        except ConnectionError:
            self.log.warning(
                f"Connection error by peer {connection.get_peername()}, closing connection."
            )
        except ssl.SSLError as e:
            self.log.warning(
                f"SSLError {e} in connection with peer {connection.get_peername()}."
            )
        except (
            concurrent.futures._base.CancelledError,
            OSError,
            TimeoutError,
            asyncio.TimeoutError,
        ) as e:
            tb = traceback.format_exc()
            self.log.error(tb)
            self.log.error(
                f"Timeout/OSError {e} in connection with peer {connection.get_peername()}, closing connection."
            )
        finally:
            # Removes the connection from the global list, so we don't try to send things to it
            global_connections.close(connection, True)

    async def handle_message(
        self, triple: Tuple[Connection, Message, PeerConnections], api: Any
    ) -> AsyncGenerator[Tuple[Connection, OutboundMessage, PeerConnections], None]:
        """
        Async generator which takes messages, parses, them, executes the right
        api function, and yields responses (to same connection, propagated, etc).
        """
        connection, full_message, global_connections = triple
        assert global_connections == self.global_connections

        try:
            if len(full_message.function) == 0 or full_message.function.startswith("_"):
                # This prevents remote calling of private methods that start with "_"
                raise ProtocolError(
                    Err.INVALID_PROTOCOL_MESSAGE, [full_message.function]
                )

            self.log.info(
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

            f_with_peer_name = getattr(
                api, full_message.function + "_with_peer_name", None
            )

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
            self.log.error(f"Error, closing connection {connection}. {tb}")
            # TODO: Exception means peer gave us invalid information, so ban this peer.
            global_connections.close(connection)

    async def expand_outbound_messages(
        self, triple: Tuple[Connection, OutboundMessage, PeerConnections]
    ) -> AsyncGenerator[Tuple[Connection, Optional[Message]], None]:
        """
        Expands each of the outbound messages into it's own message.
        """

        connection, outbound_message, global_connections = triple
        assert global_connections == self.global_connections

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
