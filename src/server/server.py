import asyncio
import logging
from pathlib import Path
import ssl
from secrets import token_bytes
from typing import Any, AsyncGenerator, List, Optional, Tuple, Dict, Callable

from aiter import iter_to_aiter, map_aiter, push_aiter
from aiter.server import start_server_aiter

from src.protocols.shared_protocol import Ping
from src.server.connection import OnConnectFunc, PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util.config import config_path_for_filename
from src.util.network import create_node_id

from .pipeline import initialize_pipeline


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
        self._local_type = local_type  # NodeType (farmer, full node, timelord, pool, harvester, wallet)

        self._ping_interval = ping_interval
        # (StreamReader, StreamWriter, NodeType) aiter, gets things from server and clients and
        # sends them through the pipeline
        self._srwt_aiter: push_aiter = push_aiter()

        # Aiter used to broadcase messages
        self._outbound_aiter: push_aiter = push_aiter()

        # Taks list to keep references to tasks, so they don'y get GCd
        self._tasks: List[asyncio.Task] = [self._initialize_ping_task()]
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        # Our unique random node id that we will send to other peers, regenerated on launch
        node_id = create_node_id()

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

    def set_state_changed_callback(self, callback: Callable):
        self.global_connections.set_state_changed_callback(callback)

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
