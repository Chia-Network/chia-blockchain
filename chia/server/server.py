import asyncio
import logging
import ssl
import time
import traceback
from ipaddress import IPv6Address, ip_address, ip_network, IPv4Network, IPv6Network
from pathlib import Path
from secrets import token_bytes
from typing import Any, Callable, Dict, List, Optional, Union, Set, Tuple

from aiohttp import ClientSession, ClientTimeout, ServerDisconnectedError, WSCloseCode, client_exceptions, web
from aiohttp.web_app import Application
from aiohttp.web_runner import TCPSite
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import protocol_version
from chia.server.introducer_peers import IntroducerPeers
from chia.server.outbound_message import Message, NodeType
from chia.server.ssl_context import private_ssl_paths, public_ssl_paths
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.errors import Err, ProtocolError
from chia.util.ints import uint16
from chia.util.network import is_localhost, is_in_network


def ssl_context_for_server(
    ca_cert: Path, ca_key: Path, private_cert_path: Path, private_key_path: Path
) -> Optional[ssl.SSLContext]:
    ssl_context = ssl._create_unverified_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=str(ca_cert))
    ssl_context.check_hostname = False
    ssl_context.load_cert_chain(certfile=str(private_cert_path), keyfile=str(private_key_path))
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    return ssl_context


def ssl_context_for_root(
    ca_cert_file: str,
) -> Optional[ssl.SSLContext]:
    ssl_context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=ca_cert_file)
    return ssl_context


def ssl_context_for_client(
    ca_cert: Path,
    ca_key: Path,
    private_cert_path: Path,
    private_key_path: Path,
) -> Optional[ssl.SSLContext]:
    ssl_context = ssl._create_unverified_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=str(ca_cert))
    ssl_context.check_hostname = False
    ssl_context.load_cert_chain(certfile=str(private_cert_path), keyfile=str(private_key_path))
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    return ssl_context


class ChiaServer:
    def __init__(
        self,
        port: int,
        node: Any,
        api: Any,
        local_type: NodeType,
        ping_interval: int,
        network_id: str,
        inbound_rate_limit_percent: int,
        outbound_rate_limit_percent: int,
        root_path: Path,
        config: Dict,
        private_ca_crt_key: Tuple[Path, Path],
        chia_ca_crt_key: Tuple[Path, Path],
        name: str = None,
        introducer_peers: Optional[IntroducerPeers] = None,
    ):
        # Keeps track of all connections to and from this node.
        logging.basicConfig(level=logging.DEBUG)
        self.all_connections: Dict[bytes32, WSChiaConnection] = {}
        self.tasks: Set[asyncio.Task] = set()

        self.connection_by_type: Dict[NodeType, Dict[bytes32, WSChiaConnection]] = {
            NodeType.FULL_NODE: {},
            NodeType.WALLET: {},
            NodeType.HARVESTER: {},
            NodeType.FARMER: {},
            NodeType.TIMELORD: {},
            NodeType.INTRODUCER: {},
        }

        self._port = port  # TCP port to identify our node
        self._local_type: NodeType = local_type

        self._ping_interval = ping_interval
        self._network_id = network_id
        self._inbound_rate_limit_percent = inbound_rate_limit_percent
        self._outbound_rate_limit_percent = outbound_rate_limit_percent

        # Task list to keep references to tasks, so they don't get GCd
        self._tasks: List[asyncio.Task] = []

        self.log = logging.getLogger(name if name else __name__)

        # Our unique random node id that we will send to other peers, regenerated on launch
        self.api = api
        self.node = node
        self.root_path = root_path
        self.config = config
        self.on_connect: Optional[Callable] = None
        self.incoming_messages: asyncio.Queue = asyncio.Queue()
        self.shut_down_event = asyncio.Event()

        if self._local_type is NodeType.INTRODUCER:
            self.introducer_peers = IntroducerPeers()

        if self._local_type is not NodeType.INTRODUCER:
            self._private_cert_path, self._private_key_path = private_ssl_paths(root_path, config)
        if self._local_type is not NodeType.HARVESTER:
            self.p2p_crt_path, self.p2p_key_path = public_ssl_paths(root_path, config)
        else:
            self.p2p_crt_path, self.p2p_key_path = None, None
        self.ca_private_crt_path, self.ca_private_key_path = private_ca_crt_key
        self.chia_ca_crt_path, self.chia_ca_key_path = chia_ca_crt_key
        self.node_id = self.my_id()

        self.incoming_task = asyncio.create_task(self.incoming_api_task())
        self.gc_task: asyncio.Task = asyncio.create_task(self.garbage_collect_connections_task())
        self.app: Optional[Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[TCPSite] = None

        self.connection_close_task: Optional[asyncio.Task] = None
        self.site_shutdown_task: Optional[asyncio.Task] = None
        self.app_shut_down_task: Optional[asyncio.Task] = None
        self.received_message_callback: Optional[Callable] = None
        self.api_tasks: Dict[bytes32, asyncio.Task] = {}
        self.execute_tasks: Set[bytes32] = set()

        self.tasks_from_peer: Dict[bytes32, Set[bytes32]] = {}
        self.banned_peers: Dict[str, float] = {}
        self.invalid_protocol_ban_seconds = 10
        self.api_exception_ban_seconds = 10
        self.exempt_peer_networks: List[Union[IPv4Network, IPv6Network]] = [
            ip_network(net, strict=False) for net in config.get("exempt_peer_networks", [])
        ]

    def my_id(self) -> bytes32:
        """If node has public cert use that one for id, if not use private."""
        if self.p2p_crt_path is not None:
            pem_cert = x509.load_pem_x509_certificate(self.p2p_crt_path.read_bytes(), default_backend())
        else:
            pem_cert = x509.load_pem_x509_certificate(self._private_cert_path.read_bytes(), default_backend())
        der_cert_bytes = pem_cert.public_bytes(encoding=serialization.Encoding.DER)
        der_cert = x509.load_der_x509_certificate(der_cert_bytes, default_backend())
        return bytes32(der_cert.fingerprint(hashes.SHA256()))

    def set_received_message_callback(self, callback: Callable):
        self.received_message_callback = callback

    async def garbage_collect_connections_task(self) -> None:
        """
        Periodically checks for connections with no activity (have not sent us any data), and removes them,
        to allow room for other peers.
        """
        while True:
            await asyncio.sleep(600)
            to_remove: List[WSChiaConnection] = []
            for connection in self.all_connections.values():
                if self._local_type == NodeType.FULL_NODE and connection.connection_type == NodeType.FULL_NODE:
                    if time.time() - connection.last_message_time > 1800:
                        to_remove.append(connection)
            for connection in to_remove:
                self.log.debug(f"Garbage collecting connection {connection.peer_host} due to inactivity")
                await connection.close()

            # Also garbage collect banned_peers dict
            to_remove_ban = []
            for peer_ip, ban_until_time in self.banned_peers.items():
                if time.time() > ban_until_time:
                    to_remove_ban.append(peer_ip)
            for peer_ip in to_remove_ban:
                del self.banned_peers[peer_ip]

    async def start_server(self, on_connect: Callable = None):
        if self._local_type in [NodeType.WALLET, NodeType.HARVESTER, NodeType.TIMELORD]:
            return None

        self.app = web.Application()
        self.on_connect = on_connect
        routes = [
            web.get("/ws", self.incoming_connection),
        ]
        self.app.add_routes(routes)
        self.runner = web.AppRunner(self.app, access_log=None, logger=self.log)
        await self.runner.setup()
        authenticate = self._local_type not in (NodeType.FULL_NODE, NodeType.INTRODUCER)
        if authenticate:
            ssl_context = ssl_context_for_server(
                self.ca_private_crt_path, self.ca_private_key_path, self._private_cert_path, self._private_key_path
            )
        else:
            self.p2p_crt_path, self.p2p_key_path = public_ssl_paths(self.root_path, self.config)
            ssl_context = ssl_context_for_server(
                self.chia_ca_crt_path, self.chia_ca_key_path, self.p2p_crt_path, self.p2p_key_path
            )

        self.site = web.TCPSite(
            self.runner,
            port=self._port,
            shutdown_timeout=3,
            ssl_context=ssl_context,
        )
        await self.site.start()
        self.log.info(f"Started listening on port: {self._port}")

    async def incoming_connection(self, request):
        if request.remote in self.banned_peers and time.time() < self.banned_peers[request.remote]:
            self.log.warning(f"Peer {request.remote} is banned, refusing connection")
            return None
        ws = web.WebSocketResponse(max_msg_size=50 * 1024 * 1024)
        await ws.prepare(request)
        close_event = asyncio.Event()
        cert_bytes = request.transport._ssl_protocol._extra["ssl_object"].getpeercert(True)
        der_cert = x509.load_der_x509_certificate(cert_bytes)
        peer_id = bytes32(der_cert.fingerprint(hashes.SHA256()))
        if peer_id == self.node_id:
            return ws
        connection: Optional[WSChiaConnection] = None
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
                peer_id,
                self._inbound_rate_limit_percent,
                self._outbound_rate_limit_percent,
                close_event,
            )
            handshake = await connection.perform_handshake(
                self._network_id,
                protocol_version,
                self._port,
                self._local_type,
            )

            assert handshake is True
            # Limit inbound connections to config's specifications.
            if not self.accept_inbound_connections(connection.connection_type) and not is_in_network(
                connection.peer_host, self.exempt_peer_networks
            ):
                self.log.info(f"Not accepting inbound connection: {connection.get_peer_info()}.Inbound limit reached.")
                await connection.close()
                close_event.set()
            else:
                await self.connection_added(connection, self.on_connect)
                if self._local_type is NodeType.INTRODUCER and connection.connection_type is NodeType.FULL_NODE:
                    self.introducer_peers.add(connection.get_peer_info())
        except ProtocolError as e:
            if connection is not None:
                await connection.close(self.invalid_protocol_ban_seconds, WSCloseCode.PROTOCOL_ERROR, e.code)
            if e.code == Err.INVALID_HANDSHAKE:
                self.log.warning("Invalid handshake with peer. Maybe the peer is running old software.")
                close_event.set()
            elif e.code == Err.INCOMPATIBLE_NETWORK_ID:
                self.log.warning("Incompatible network ID. Maybe the peer is on another network")
                close_event.set()
            elif e.code == Err.SELF_CONNECTION:
                close_event.set()
            else:
                error_stack = traceback.format_exc()
                self.log.error(f"Exception {e}, exception Stack: {error_stack}")
                close_event.set()
        except Exception as e:
            if connection is not None:
                await connection.close(ws_close_code=WSCloseCode.PROTOCOL_ERROR, error=Err.UNKNOWN)
            error_stack = traceback.format_exc()
            self.log.error(f"Exception {e}, exception Stack: {error_stack}")
            close_event.set()

        await close_event.wait()
        return ws

    async def connection_added(self, connection: WSChiaConnection, on_connect=None):
        # If we already had a connection to this peer_id, close the old one. This is secure because peer_ids are based
        # on TLS public keys
        if connection.peer_node_id in self.all_connections:
            con = self.all_connections[connection.peer_node_id]
            await con.close()
        self.all_connections[connection.peer_node_id] = connection
        if connection.connection_type is not None:
            self.connection_by_type[connection.connection_type][connection.peer_node_id] = connection
            if on_connect is not None:
                await on_connect(connection)
        else:
            self.log.error(f"Invalid connection type for connection {connection}")

    def is_duplicate_or_self_connection(self, target_node: PeerInfo) -> bool:
        if is_localhost(target_node.host) and target_node.port == self._port:
            # Don't connect to self
            self.log.debug(f"Not connecting to {target_node}")
            return True
        for connection in self.all_connections.values():
            if connection.host == target_node.host and connection.peer_server_port == target_node.port:
                self.log.debug(f"Not connecting to {target_node}, duplicate connection")
                return True
        return False

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
        if self.is_duplicate_or_self_connection(target_node):
            return False

        if target_node.host in self.banned_peers and time.time() < self.banned_peers[target_node.host]:
            self.log.warning(f"Peer {target_node.host} is still banned, not connecting to it")
            return False

        if auth:
            ssl_context = ssl_context_for_client(
                self.ca_private_crt_path, self.ca_private_key_path, self._private_cert_path, self._private_key_path
            )
        else:
            ssl_context = ssl_context_for_client(
                self.chia_ca_crt_path, self.chia_ca_key_path, self.p2p_crt_path, self.p2p_key_path
            )
        session = None
        connection: Optional[WSChiaConnection] = None
        try:
            timeout = ClientTimeout(total=30)
            session = ClientSession(timeout=timeout)

            try:
                if type(ip_address(target_node.host)) is IPv6Address:
                    target_node = PeerInfo(f"[{target_node.host}]", target_node.port)
            except ValueError:
                pass

            url = f"wss://{target_node.host}:{target_node.port}/ws"
            self.log.debug(f"Connecting: {url}, Peer info: {target_node}")
            try:
                ws = await session.ws_connect(
                    url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=50 * 1024 * 1024
                )
            except ServerDisconnectedError:
                self.log.debug(f"Server disconnected error connecting to {url}. Perhaps we are banned by the peer.")
                return False
            except asyncio.TimeoutError:
                self.log.debug(f"Timeout error connecting to {url}")
                return False
            if ws is None:
                return False

            assert ws._response.connection is not None and ws._response.connection.transport is not None
            transport = ws._response.connection.transport  # type: ignore
            cert_bytes = transport._ssl_protocol._extra["ssl_object"].getpeercert(True)  # type: ignore
            der_cert = x509.load_der_x509_certificate(cert_bytes, default_backend())
            peer_id = bytes32(der_cert.fingerprint(hashes.SHA256()))
            if peer_id == self.node_id:
                raise RuntimeError(f"Trying to connect to a peer ({target_node}) with the same peer_id: {peer_id}")

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
                peer_id,
                self._inbound_rate_limit_percent,
                self._outbound_rate_limit_percent,
                session=session,
            )
            handshake = await connection.perform_handshake(
                self._network_id,
                protocol_version,
                self._port,
                self._local_type,
            )
            assert handshake is True
            await self.connection_added(connection, on_connect)
            # the session has been adopted by the connection, don't close it at
            # the end of the function
            session = None
            connection_type_str = ""
            if connection.connection_type is not None:
                connection_type_str = connection.connection_type.name.lower()
            self.log.info(f"Connected with {connection_type_str} {target_node}")
            if is_feeler:
                asyncio.create_task(connection.close())
            return True
        except client_exceptions.ClientConnectorError as e:
            self.log.info(f"{e}")
        except ProtocolError as e:
            if connection is not None:
                await connection.close(self.invalid_protocol_ban_seconds, WSCloseCode.PROTOCOL_ERROR, e.code)
            if e.code == Err.INVALID_HANDSHAKE:
                self.log.warning(f"Invalid handshake with peer {target_node}. Maybe the peer is running old software.")
            elif e.code == Err.INCOMPATIBLE_NETWORK_ID:
                self.log.warning("Incompatible network ID. Maybe the peer is on another network")
            elif e.code == Err.SELF_CONNECTION:
                pass
            else:
                error_stack = traceback.format_exc()
                self.log.error(f"Exception {e}, exception Stack: {error_stack}")
        except Exception as e:
            if connection is not None:
                await connection.close(self.invalid_protocol_ban_seconds, WSCloseCode.PROTOCOL_ERROR, Err.UNKNOWN)
            error_stack = traceback.format_exc()
            self.log.error(f"Exception {e}, exception Stack: {error_stack}")
        finally:
            if session is not None:
                await session.close()

        return False

    def connection_closed(self, connection: WSChiaConnection, ban_time: int):
        if is_localhost(connection.peer_host) and ban_time != 0:
            self.log.warning(f"Trying to ban localhost for {ban_time}, but will not ban")
            ban_time = 0
        self.log.info(f"Connection closed: {connection.peer_host}, node id: {connection.peer_node_id}")
        if ban_time > 0:
            ban_until: float = time.time() + ban_time
            self.log.warning(f"Banning {connection.peer_host} for {ban_time} seconds")
            if connection.peer_host in self.banned_peers:
                if ban_until > self.banned_peers[connection.peer_host]:
                    self.banned_peers[connection.peer_host] = ban_until
            else:
                self.banned_peers[connection.peer_host] = ban_until

        if connection.peer_node_id in self.all_connections:
            self.all_connections.pop(connection.peer_node_id)
        if connection.connection_type is not None:
            if connection.peer_node_id in self.connection_by_type[connection.connection_type]:
                self.connection_by_type[connection.connection_type].pop(connection.peer_node_id)
        else:
            # This means the handshake was enver finished with this peer
            self.log.debug(
                f"Invalid connection type for connection {connection.peer_host},"
                f" while closing. Handshake never finished."
            )
        on_disconnect = getattr(self.node, "on_disconnect", None)
        if on_disconnect is not None:
            on_disconnect(connection)

        self.cancel_tasks_from_peer(connection.peer_node_id)

    def cancel_tasks_from_peer(self, peer_id: bytes32):
        if peer_id not in self.tasks_from_peer:
            return None

        task_ids = self.tasks_from_peer[peer_id]
        for task_id in task_ids:
            if task_id in self.execute_tasks:
                continue
            task = self.api_tasks[task_id]
            task.cancel()

    async def incoming_api_task(self) -> None:
        self.tasks = set()
        while True:
            payload_inc, connection_inc = await self.incoming_messages.get()
            if payload_inc is None or connection_inc is None:
                continue

            async def api_call(full_message: Message, connection: WSChiaConnection, task_id):
                start_time = time.time()
                try:
                    if self.received_message_callback is not None:
                        await self.received_message_callback(connection)
                    connection.log.debug(
                        f"<- {ProtocolMessageTypes(full_message.type).name} from peer "
                        f"{connection.peer_node_id} {connection.peer_host}"
                    )
                    message_type: str = ProtocolMessageTypes(full_message.type).name

                    f = getattr(self.api, message_type, None)

                    if f is None:
                        self.log.error(f"Non existing function: {message_type}")
                        raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [message_type])

                    if not hasattr(f, "api_function"):
                        self.log.error(f"Peer trying to call non api function {message_type}")
                        raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [message_type])

                    # If api is not ready ignore the request
                    if hasattr(self.api, "api_ready"):
                        if self.api.api_ready is False:
                            return None

                    timeout: Optional[int] = 600
                    if hasattr(f, "execute_task"):
                        # Don't timeout on methods with execute_task decorator, these need to run fully
                        self.execute_tasks.add(task_id)
                        timeout = None

                    if hasattr(f, "peer_required"):
                        coroutine = f(full_message.data, connection)
                    else:
                        coroutine = f(full_message.data)

                    async def wrapped_coroutine() -> Optional[Message]:
                        try:
                            result = await coroutine
                            return result
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            tb = traceback.format_exc()
                            connection.log.error(f"Exception: {e}, {connection.get_peer_info()}. {tb}")
                            raise e
                        return None

                    response: Optional[Message] = await asyncio.wait_for(wrapped_coroutine(), timeout=timeout)
                    connection.log.debug(
                        f"Time taken to process {message_type} from {connection.peer_node_id} is "
                        f"{time.time() - start_time} seconds"
                    )

                    if response is not None:
                        response_message = Message(response.type, full_message.id, response.data)
                        await connection.reply_to_request(response_message)
                except Exception as e:
                    if self.connection_close_task is None:
                        tb = traceback.format_exc()
                        connection.log.error(
                            f"Exception: {e} {type(e)}, closing connection {connection.get_peer_info()}. {tb}"
                        )
                    else:
                        connection.log.debug(f"Exception: {e} while closing connection")
                    # TODO: actually throw one of the errors from errors.py and pass this to close
                    await connection.close(self.api_exception_ban_seconds, WSCloseCode.PROTOCOL_ERROR, Err.UNKNOWN)
                finally:
                    if task_id in self.api_tasks:
                        self.api_tasks.pop(task_id)
                    if task_id in self.tasks_from_peer[connection.peer_node_id]:
                        self.tasks_from_peer[connection.peer_node_id].remove(task_id)
                    if task_id in self.execute_tasks:
                        self.execute_tasks.remove(task_id)

            task_id = token_bytes()
            api_task = asyncio.create_task(api_call(payload_inc, connection_inc, task_id))
            self.api_tasks[task_id] = api_task
            if connection_inc.peer_node_id not in self.tasks_from_peer:
                self.tasks_from_peer[connection_inc.peer_node_id] = set()
            self.tasks_from_peer[connection_inc.peer_node_id].add(task_id)

    async def send_to_others(
        self,
        messages: List[Message],
        node_type: NodeType,
        origin_peer: WSChiaConnection,
    ):
        for node_id, connection in self.all_connections.items():
            if node_id == origin_peer.peer_node_id:
                continue
            if connection.connection_type is node_type:
                for message in messages:
                    await connection.send_message(message)

    async def send_to_all(self, messages: List[Message], node_type: NodeType):
        for _, connection in self.all_connections.items():
            if connection.connection_type is node_type:
                for message in messages:
                    await connection.send_message(message)

    async def send_to_all_except(self, messages: List[Message], node_type: NodeType, exclude: bytes32):
        for _, connection in self.all_connections.items():
            if connection.connection_type is node_type and connection.peer_node_id != exclude:
                for message in messages:
                    await connection.send_message(message)

    async def send_to_specific(self, messages: List[Message], node_id: bytes32):
        if node_id in self.all_connections:
            connection = self.all_connections[node_id]
            for message in messages:
                await connection.send_message(message)

    def get_outgoing_connections(self) -> List[WSChiaConnection]:
        result = []
        for _, connection in self.all_connections.items():
            if connection.is_outbound:
                result.append(connection)

        return result

    def get_full_node_outgoing_connections(self) -> List[WSChiaConnection]:
        result = []
        connections = self.get_full_node_connections()
        for connection in connections:
            if connection.is_outbound:
                result.append(connection)
        return result

    def get_full_node_connections(self) -> List[WSChiaConnection]:
        return list(self.connection_by_type[NodeType.FULL_NODE].values())

    def get_connections(self) -> List[WSChiaConnection]:
        result = []
        for _, connection in self.all_connections.items():
            result.append(connection)
        return result

    async def close_all_connections(self) -> None:
        keys = [a for a, b in self.all_connections.items()]
        for node_id in keys:
            try:
                if node_id in self.all_connections:
                    connection = self.all_connections[node_id]
                    await connection.close()
            except Exception as e:
                self.log.error(f"Exception while closing connection {e}")

    def close_all(self) -> None:
        self.connection_close_task = asyncio.create_task(self.close_all_connections())
        if self.runner is not None:
            self.site_shutdown_task = asyncio.create_task(self.runner.cleanup())
        if self.app is not None:
            self.app_shut_down_task = asyncio.create_task(self.app.shutdown())
        for task_id, task in self.api_tasks.items():
            task.cancel()

        self.shut_down_event.set()
        self.incoming_task.cancel()
        self.gc_task.cancel()

    async def await_closed(self) -> None:
        self.log.debug("Await Closed")
        await self.shut_down_event.wait()
        if self.connection_close_task is not None:
            await self.connection_close_task
        if self.app_shut_down_task is not None:
            await self.app_shut_down_task
        if self.site_shutdown_task is not None:
            await self.site_shutdown_task

    async def get_peer_info(self) -> Optional[PeerInfo]:
        ip = None
        port = self._port

        try:
            async with ClientSession() as session:
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

    def accept_inbound_connections(self, node_type: NodeType) -> bool:
        if not self._local_type == NodeType.FULL_NODE:
            return True
        inbound_count = len([conn for _, conn in self.connection_by_type[node_type].items() if not conn.is_outbound])
        if node_type == NodeType.FULL_NODE:
            return inbound_count < self.config["target_peer_count"] - self.config["target_outbound_peer_count"]
        if node_type == NodeType.WALLET:
            return inbound_count < self.config["max_inbound_wallet"]
        if node_type == NodeType.FARMER:
            return inbound_count < self.config["max_inbound_farmer"]
        if node_type == NodeType.TIMELORD:
            return inbound_count < self.config["max_inbound_timelord"]
        return True

    def is_trusted_peer(self, peer: WSChiaConnection, trusted_peers: Dict) -> bool:
        if trusted_peers is None:
            return False
        for trusted_peer in trusted_peers:
            cert = self.root_path / trusted_peers[trusted_peer]
            pem_cert = x509.load_pem_x509_certificate(cert.read_bytes())
            cert_bytes = pem_cert.public_bytes(encoding=serialization.Encoding.DER)
            der_cert = x509.load_der_x509_certificate(cert_bytes)
            peer_id = bytes32(der_cert.fingerprint(hashes.SHA256()))
            if peer_id == peer.peer_node_id:
                self.log.debug(f"trusted node {peer.peer_node_id} {peer.peer_host}")
                return True
        return False
