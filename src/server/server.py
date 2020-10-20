import asyncio
import logging
import ssl
from secrets import token_bytes
from typing import Any, Callable, List, Tuple

from aiter import iter_to_aiter, map_aiter, push_aiter
from aiter.server import start_server_aiter

from src.protocols.shared_protocol import Ping
from src.server.connection import OnConnectFunc, PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util.network import create_node_id

from .pipeline import initialize_pipeline


async def start_server(
    self: "ChiaServer", on_connect: OnConnectFunc = None
) -> asyncio.AbstractServer:
    """
    Launches a listening server on host and port specified, to connect to NodeType nodes. On each
    connection, the on_connect asynchronous generator will be called, and responses will be sent.
    Whenever a new TCP connection is made, a new srwt tuple is sent through the pipeline.
    """
    require_cert = self._local_type not in (NodeType.FULL_NODE, NodeType.INTRODUCER)
    ssl_context = self.ssl_context_for_server(require_cert)

    server, aiter = await start_server_aiter(
        self._port, host=None, reuse_address=True, ssl=ssl_context
    )

    def add_connection_type(
        srw: Tuple[asyncio.StreamReader, asyncio.StreamWriter]
    ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter, OnConnectFunc, bool, bool]:
        ssl_object = srw[1].get_extra_info(name="ssl_object")
        peer_cert = ssl_object.getpeercert()
        self.log.info(f"Client authed as {peer_cert}")
        # Inbound peer, not a feeler.
        return (srw[0], srw[1], on_connect, False, False)

    srwt_aiter = map_aiter(add_connection_type, aiter)

    # Push aiters that come from the server into the pipeline
    if not self._srwt_aiter.is_stopped():
        self._srwt_aiter.push(srwt_aiter)

    self.log.info(f"Server started on port {self._port}")
    return server


class ChiaServer:
    def __init__(
        self,
        port: int,
        api: Any,
        local_type: NodeType,
        ping_interval: int,
        network_id: str,
        ssl_context_for_client: Callable[[bool], ssl.SSLContext],
        ssl_context_for_server: Callable[[bool], ssl.SSLContext],
        name: str = None,
    ):
        # Keeps track of all connections to and from this node.
        self.global_connections: PeerConnections = PeerConnections(local_type, [])

        self._port = port  # TCP port to identify our node
        self._local_type = local_type  # NodeType (farmer, full node, timelord, pool, harvester, wallet)

        self._ping_interval = ping_interval
        # (StreamReader, StreamWriter, NodeType) aiter, gets things from server and clients and
        # sends them through the pipeline
        self._srwt_aiter: push_aiter = push_aiter()

        # Aiter used to broadcase messages
        self._outbound_aiter: push_aiter = push_aiter()

        # Open connection tasks. These will be cancelled if
        self._oc_tasks: List[asyncio.Task] = []

        # Taks list to keep references to tasks, so they don'y get GCd
        self._tasks: List[asyncio.Task] = []
        if local_type != NodeType.INTRODUCER:
            # Introducers should not keep connections alive, they should close them
            self._tasks.append(self._initialize_ping_task())

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        # Our unique random node id that we will send to other peers, regenerated on launch
        node_id = create_node_id()

        if hasattr(api, "_set_global_connections"):
            api._set_global_connections(self.global_connections)

        # Tasks for entire server pipeline
        self._pipeline_task: asyncio.Future = asyncio.ensure_future(
            initialize_pipeline(
                self._srwt_aiter,
                api,
                self._port,
                self._outbound_aiter,
                self.global_connections,
                self._local_type,
                node_id,
                network_id,
                self.log,
            )
        )

        self.ssl_context_for_client = ssl_context_for_client
        self.ssl_context_for_server = ssl_context_for_server

        self._pending_connections: List = []

    async def start_client(
        self,
        target_node: PeerInfo,
        on_connect: OnConnectFunc = None,
        auth: bool = False,
        is_feeler: bool = False,
    ) -> bool:
        """
        Tries to connect to the target node, adding one connection into the pipeline, if successful.
        An on connect method can also be specified, and this will be saved into the instance variables.
        """
        self.log.info(f"Trying to connect with {target_node}.")
        if self._pipeline_task.done():
            self.log.error("Starting client after server closed")
            return False

        ssl_context = self.ssl_context_for_client(auth)
        try:
            # Sometimes open_connection takes a long time, so we add it as a task, and cancel
            # the task in the event of closing the node.
            peer_info = (target_node.host, target_node.port)
            if peer_info in self._pending_connections:
                return False
            self._pending_connections.append(peer_info)
            oc_task: asyncio.Task = asyncio.create_task(
                asyncio.open_connection(
                    target_node.host, int(target_node.port), ssl=ssl_context
                )
            )
            self._oc_tasks.append(oc_task)
            reader, writer = await oc_task
            self._pending_connections.remove(peer_info)
            self._oc_tasks.remove(oc_task)
        except Exception as e:
            self.log.warning(
                f"Could not connect to {target_node}. {type(e)}{str(e)}. Aborting and removing peer."
            )
            self.global_connections.failed_connection(target_node)
            if self.global_connections.introducer_peers is not None:
                self.global_connections.introducer_peers.remove(target_node)
            if peer_info in self._pending_connections:
                self._pending_connections.remove(peer_info)
            return False
        if not self._srwt_aiter.is_stopped():
            self._srwt_aiter.push(
                iter_to_aiter([(reader, writer, on_connect, True, is_feeler)])
            )

        ssl_object = writer.get_extra_info(name="ssl_object")
        peer_cert = ssl_object.getpeercert()
        self.log.info(f"Server authed as {peer_cert}")

        return True

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
        if not self._outbound_aiter.is_stopped():
            self._outbound_aiter.stop()
        if not self._srwt_aiter.is_stopped():
            self._srwt_aiter.stop()
        for task in self._oc_tasks:
            task.cancel()

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
