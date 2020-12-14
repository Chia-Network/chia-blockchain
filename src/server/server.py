import asyncio
import logging
import time
from asyncio import Queue
from copy import copy
from pathlib import Path
from typing import Any, List, Dict, Tuple, Callable, Optional

import aiohttp
from aiohttp import web
from src.server.introducer_peers import IntroducerPeers
from src.server.outbound_message import NodeType, Message
from src.server.ws_connection import WSChiaConnection
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util.errors import ProtocolError, Err
from src.util.ints import uint16
from src.util.network import create_node_id
from src.protocols.shared_protocol import protocol_version, Ping, Pong
import traceback


class ChiaServer:
    def __init__(
        self,
        port: int,
        api: Any,
        local_type: NodeType,
        ping_interval: int,
        network_id: str,
        private_cert_path: Path,
        private_key_path: Path,
        name: str = None,
    ):
        # Keeps track of all connections to and from this node.
        self.global_connections: Dict[bytes32, WSChiaConnection] = {}
        self.full_nodes: Dict[str, WSChiaConnection] = {}
        self.wallets: Dict[str, WSChiaConnection] = {}

        self.connection_by_type: Dict[NodeType, Dict[str, WSChiaConnection]] = {}
        self._port = port  # TCP port to identify our node
        self._local_type: NodeType = local_type

        self._ping_interval = ping_interval
        self._network_id = network_id
        # Open connection tasks. These will be cancelled if
        self._oc_tasks: List[asyncio.Task] = []

        # Taks list to keep references to tasks, so they don'y get GCd
        self._tasks: List[asyncio.Task] = []

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        # Our unique random node id that we will send to other peers, regenerated on launch
        self.node_id = create_node_id()
        self.api = api
        self.root_path = root_path
        self.config = config
        self.on_connect: Optional[Callable] = None
        self.incoming_messages: Queue[
            Tuple[Message, WSChiaConnection]
        ] = asyncio.Queue()
        self.shut_down_event = asyncio.Event()

        if self._local_type is NodeType.INTRODUCER:
            self.introducer_peers = IntroducerPeers()

        self.incoming_task = asyncio.create_task(self.incoming_api_task())
        self.app = None
        self.site = None

    async def start_server(self, on_connect: Callable = None):
        self.app = web.Application()
        self.on_connect = on_connect
        routes = [
            web.get("/ws", self.incoming_connection),
        ]
        self.app.add_routes(routes)
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, port=self._port, shutdown_timeout=3)
        await self.site.start()
        self.log.info(f"Started listening on port: {self._port}")

    async def incoming_connection(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        close_event = asyncio.Event()

        try:
            connection = WSChiaConnection(
                self._local_type,
                ws,
                self._port,
                self.log,
                False,
                False,
                request.remote,
                self.incoming_messages,
                self.connection_closed,
                close_event,
            )
            handshake = await connection.perform_handshake(
                self._network_id,
                protocol_version,
                self.node_id,
                self._port,
                self._local_type,
            )

            assert handshake is True
            self.global_connections[connection.peer_node_id] = connection
            if self.on_connect is not None:
                await self.on_connect(connection)
            if (
                self._local_type is NodeType.INTRODUCER
                and connection.connection_type is NodeType.FULL_NODE
            ):
                self.introducer_peers.add(connection.get_peer_info())
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception Stack: {error_stack}")
            close_event.set()

        await close_event.wait()
        return ws

    async def start_client(
        self,
        target_node: PeerInfo,
        on_connect: Callable = None,
        auth: bool = False,
        is_feeler: bool = False,
    ) -> bool:
        """
        Tries to connect to the target node, adding one connection into the pipeline, if successful.
        An on connect method can also be specified, and this will be saved into the instance variables.
        """
        session = None
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            session = aiohttp.ClientSession(timeout=timeout)
            url = f"ws://{target_node.host}:{target_node.port}/ws"
            self.log.info(f"Connecting: {url}")
            ws = await session.ws_connect(
                url,
                autoclose=False,
                autoping=True,
            )
            if ws is not None:
                connection = WSChiaConnection(
                    self._local_type,
                    ws,
                    self._port,
                    self.log,
                    True,
                    False,
                    target_node.host,
                    self.incoming_messages,
                    self.connection_closed,
                    session=session,
                )
                handshake = await connection.perform_handshake(
                    self._network_id,
                    protocol_version,
                    self.node_id,
                    self._port,
                    self._local_type,
                )
                assert handshake is True
                if on_connect is not None:
                    await on_connect(connection)
                self.global_connections[connection.peer_node_id] = connection
                self.log.info("Connected")
            return True
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            if session is not None:
                await session.close()
            self.log.error(f"Exception Stack: {error_stack}")

        return False

    def connection_closed(self, connection: WSChiaConnection):
        self.log.info(f"Connection closed: {connection.peer_host}")
        if connection.peer_node_id in self.global_connections:
            self.global_connections.pop(connection.peer_node_id)

    async def incoming_api_task(self):
        self.tasks = set()
        while True:
            full_message, connection = await self.incoming_messages.get()
            if full_message is None or connection is None:
                continue

            async def api_call(full_message, connection):
                try:
                    connection.log.info(
                        f"<- {full_message.function} from peer {connection.peer_node_id}"
                    )
                    if len(
                        full_message.function
                    ) == 0 or full_message.function.startswith("_"):
                        # This prevents remote calling of private methods that start with "_"
                        self.log.error(
                            f"Non existing function: {full_message.function}"
                        )
                        raise ProtocolError(
                            Err.INVALID_PROTOCOL_MESSAGE, [full_message.function]
                        )

                    f = getattr(self.api, full_message.function, None)

                    if f is None:
                        self.log.error(
                            f"Non existing function: {full_message.function}"
                        )
                        raise ProtocolError(
                            Err.INVALID_PROTOCOL_MESSAGE, [full_message.function]
                        )

                    if hasattr(f, "peer_required"):
                        response = await f(full_message.data, connection)
                    else:
                        response = await f(full_message.data)

                    if response is not None:
                        await connection.send_message(response)

                except Exception as e:
                    tb = traceback.format_exc()
                    connection.log.error(
                        f"Exception: {e}, closing connection {connection}. {tb}"
                    )
                    await connection.close()

            asyncio.create_task(api_call(full_message, connection))

    async def send_to_others(
        self, messages: List[Message], type: NodeType, origin_peer: WSChiaConnection
    ):
        for id, connection in self.global_connections.items():
            if id == origin_peer.peer_node_id:
                continue
            if connection.connection_type is type:
                for message in messages:
                    await connection.outgoing_queue.put(message)

    async def send_to_all(self, messages: List[Message], type: NodeType):
        for id, connection in self.global_connections.items():
            if connection.connection_type is type:
                for message in messages:
                    await connection.send_message(message)

    async def send_to_specific(self, messages: List[Message], node_id: bytes32):
        if node_id in self.global_connections:
            connection = self.global_connections[node_id]
            for message in messages:
                await connection.send_message(message)

    def get_outgoing_connections(self) -> List[WSChiaConnection]:
        result = []
        for id, connection in self.global_connections.items():
            if connection.is_outbound:
                result.append(connection)

        return result

    def get_full_node_connections(self) -> List[WSChiaConnection]:
        result = []
        for id, connection in self.global_connections.items():
            if connection.connection_type is NodeType.FULL_NODE:
                result.append(connection)

        return result

    def get_connections(self) -> List[WSChiaConnection]:
        result = []
        for id, connection in self.global_connections.items():
            result.append(connection)
        return result

    async def close_all_connections(self):
        keys = [a for a, b in self.global_connections.items()]
        for id in keys:
            try:
                if id in self.global_connections:
                    connection = self.global_connections[id]
                    await connection.close()
            except Exception as e:
                self.log.error(f"exeption while closing connection {e}")

    def close_all(self):
        self.connection_close_taks = asyncio.create_task(self.close_all_connections())
        self.site_shutdown_task = asyncio.create_task(self.runner.cleanup())
        self.app_shut_down_task = asyncio.create_task(self.app.shutdown())

        self.shut_down_event.set()
        if self.incoming_task is not None:
            self.incoming_task.cancel()

    async def await_closed(self):
        self.log.info("Await Closed")
        await self.shut_down_event.wait()
        await self.connection_close_taks
        await self.app_shut_down_task
        await self.site_shutdown_task

    async def get_peer_info(self) -> Optional[PeerInfo]:
        ip = None
        port = self._port

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://checkip.amazonaws.com/") as resp:
                    if resp.status == 200:
                        ip = str(await resp.text())
                        ip = ip.rstrip()
        except Exception:
            ip = None
        if ip is None:
            return None
        peer = PeerInfo(ip, uint16(port))
        if not peer.is_valid():
            return None
        return peer
