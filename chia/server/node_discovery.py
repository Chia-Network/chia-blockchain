import asyncio
import math
import time
import traceback
from pathlib import Path
from random import Random
from secrets import randbits
from typing import Dict, Optional, List, Set

import aiosqlite

import chia.server.ws_connection as ws
import dns.asyncresolver
from chia.protocols import full_node_protocol, introducer_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.address_manager import AddressManager, ExtendedPeerInfo
from chia.server.address_manager_store import AddressManagerStore
from chia.server.outbound_message import NodeType, make_msg
from chia.server.server import ChiaServer
from chia.types.peer_info import PeerInfo, TimestampedPeerInfo
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.util.path import mkdir, path_from_root

MAX_PEERS_RECEIVED_PER_REQUEST = 1000
MAX_TOTAL_PEERS_RECEIVED = 3000
MAX_CONCURRENT_OUTBOUND_CONNECTIONS = 70
NETWORK_ID_DEFAULT_PORTS = {
    "mainnet": 8444,
    "testnet7": 58444,
    "testnet8": 58445,
}


class FullNodeDiscovery:
    resolver: Optional[dns.asyncresolver.Resolver]

    def __init__(
        self,
        server: ChiaServer,
        root_path: Path,
        target_outbound_count: int,
        peer_db_path: str,
        introducer_info: Optional[Dict],
        dns_servers: List[str],
        peer_connect_interval: int,
        selected_network: str,
        default_port: Optional[int],
        log,
    ):
        self.server: ChiaServer = server
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.is_closed = False
        self.target_outbound_count = target_outbound_count
        # This is a double check to make sure testnet and mainnet peer databases never mix up.
        # If the network is not 'mainnet', it names the peer db differently, including the selected_network.
        if selected_network != "mainnet":
            if not peer_db_path.endswith(".sqlite"):
                raise ValueError(f"Invalid path for peer table db: {peer_db_path}. Make the path end with .sqlite")
            peer_db_path = peer_db_path[:-7] + "_" + selected_network + ".sqlite"
        self.peer_db_path = path_from_root(root_path, peer_db_path)
        self.dns_servers = dns_servers
        if introducer_info is not None:
            self.introducer_info: Optional[PeerInfo] = PeerInfo(
                introducer_info["host"],
                introducer_info["port"],
            )
        else:
            self.introducer_info = None
        self.peer_connect_interval = peer_connect_interval
        self.log = log
        self.relay_queue = None
        self.address_manager: Optional[AddressManager] = None
        self.connection_time_pretest: Dict = {}
        self.received_count_from_peers: Dict = {}
        self.lock = asyncio.Lock()
        self.connect_peers_task: Optional[asyncio.Task] = None
        self.serialize_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.initial_wait: int = 0
        try:
            self.resolver: Optional[dns.asyncresolver.Resolver] = dns.asyncresolver.Resolver()
        except Exception:
            self.resolver = None
            self.log.exception("Error initializing asyncresolver")
        self.pending_outbound_connections: Set[str] = set()
        self.pending_tasks: Set[asyncio.Task] = set()
        self.default_port: Optional[int] = default_port
        if default_port is None and selected_network in NETWORK_ID_DEFAULT_PORTS:
            self.default_port = NETWORK_ID_DEFAULT_PORTS[selected_network]

    async def initialize_address_manager(self) -> None:
        mkdir(self.peer_db_path.parent)
        self.connection = await aiosqlite.connect(self.peer_db_path)
        await self.connection.execute("pragma journal_mode=wal")
        await self.connection.execute("pragma synchronous=OFF")
        self.address_manager_store = await AddressManagerStore.create(self.connection)
        if not await self.address_manager_store.is_empty():
            self.address_manager = await self.address_manager_store.deserialize()
        else:
            await self.address_manager_store.clear()
            self.address_manager = AddressManager()
        self.server.set_received_message_callback(self.update_peer_timestamp_on_message)

    async def start_tasks(self) -> None:
        random = Random()
        self.connect_peers_task = asyncio.create_task(self._connect_to_peers(random))
        self.serialize_task = asyncio.create_task(self._periodically_serialize(random))
        self.cleanup_task = asyncio.create_task(self._periodically_cleanup())

    async def _close_common(self) -> None:
        self.is_closed = True
        self.cancel_task_safe(self.connect_peers_task)
        self.cancel_task_safe(self.serialize_task)
        self.cancel_task_safe(self.cleanup_task)
        for t in self.pending_tasks:
            self.cancel_task_safe(t)
        if len(self.pending_tasks) > 0:
            await asyncio.wait(self.pending_tasks)
        await self.connection.close()

    def cancel_task_safe(self, task: Optional[asyncio.Task]):
        if task is not None:
            try:
                task.cancel()
            except Exception as e:
                self.log.error(f"Error while canceling task.{e} {task}")

    def add_message(self, message, data):
        self.message_queue.put_nowait((message, data))

    async def on_connect(self, peer: ws.WSChiaConnection):
        if (
            peer.is_outbound is False
            and peer.peer_server_port is not None
            and peer.connection_type is NodeType.FULL_NODE
            and self.server._local_type is NodeType.FULL_NODE
            and self.address_manager is not None
        ):
            timestamped_peer_info = TimestampedPeerInfo(
                peer.peer_host,
                peer.peer_server_port,
                uint64(int(time.time())),
            )
            await self.address_manager.add_to_new_table([timestamped_peer_info], peer.get_peer_info(), 0)
            if self.relay_queue is not None:
                self.relay_queue.put_nowait((timestamped_peer_info, 1))
        if (
            peer.is_outbound
            and peer.peer_server_port is not None
            and peer.connection_type is NodeType.FULL_NODE
            and (self.server._local_type is NodeType.FULL_NODE or self.server._local_type is NodeType.WALLET)
            and self.address_manager is not None
        ):
            msg = make_msg(ProtocolMessageTypes.request_peers, full_node_protocol.RequestPeers())
            await peer.send_message(msg)

    # Updates timestamps each time we receive a message for outbound connections.
    async def update_peer_timestamp_on_message(self, peer: ws.WSChiaConnection):
        if (
            peer.is_outbound
            and peer.peer_server_port is not None
            and peer.connection_type is NodeType.FULL_NODE
            and self.server._local_type is NodeType.FULL_NODE
            and self.address_manager is not None
        ):
            peer_info = peer.get_peer_info()
            if peer_info is None:
                return None
            if peer_info.host not in self.connection_time_pretest:
                self.connection_time_pretest[peer_info.host] = time.time()
            if time.time() - self.connection_time_pretest[peer_info.host] > 600:
                self.connection_time_pretest[peer_info.host] = time.time()
                await self.address_manager.connect(peer_info)

    def _num_needed_peers(self) -> int:
        target = self.target_outbound_count
        outgoing = len(self.server.get_full_node_outgoing_connections())
        return max(0, target - outgoing)

    """
    Uses the Poisson distribution to determine the next time
    when we'll initiate a feeler connection.
    (https://en.wikipedia.org/wiki/Poisson_distribution)
    """

    def _poisson_next_send(self, now, avg_interval_seconds, random):
        return now + (
            math.log(random.randrange(1 << 48) * -0.0000000000000035527136788 + 1) * avg_interval_seconds * -1000000.0
            + 0.5
        )

    async def _introducer_client(self):
        if self.introducer_info is None:
            return None

        async def on_connect(peer: ws.WSChiaConnection):
            msg = make_msg(ProtocolMessageTypes.request_peers_introducer, introducer_protocol.RequestPeersIntroducer())
            await peer.send_message(msg)

        await self.server.start_client(self.introducer_info, on_connect)

    async def _query_dns(self, dns_address):
        try:
            if self.default_port is None:
                self.log.error(
                    "Network id not supported in NETWORK_ID_DEFAULT_PORTS neither in config. Skipping DNS query."
                )
                return
            if self.resolver is None:
                self.log.warn("Skipping DNS query: asyncresolver not initialized.")
                return
            for rdtype in ["A", "AAAA"]:
                peers: List[TimestampedPeerInfo] = []
                result = await self.resolver.resolve(qname=dns_address, rdtype=rdtype, lifetime=30)
                for ip in result:
                    peers.append(
                        TimestampedPeerInfo(
                            ip.to_text(),
                            self.default_port,
                            0,
                        )
                    )
                self.log.info(f"Received {len(peers)} peers from DNS seeder, using rdtype = {rdtype}.")
                if len(peers) > 0:
                    await self._respond_peers_common(full_node_protocol.RespondPeers(peers), None, False)
        except Exception as e:
            self.log.warn(f"querying DNS introducer failed: {e}")

    async def start_client_async(self, addr: PeerInfo, is_feeler: bool) -> None:
        try:
            if self.address_manager is None:
                return
            self.pending_outbound_connections.add(addr.host)
            client_connected = await self.server.start_client(
                addr,
                on_connect=self.server.on_connect,
                is_feeler=is_feeler,
            )
            if self.server.is_duplicate_or_self_connection(addr):
                # Mark it as a softer attempt, without counting the failures.
                await self.address_manager.attempt(addr, False)
            else:
                if client_connected is True:
                    await self.address_manager.mark_good(addr)
                    await self.address_manager.connect(addr)
                else:
                    await self.address_manager.attempt(addr, True)
            self.pending_outbound_connections.remove(addr.host)
        except Exception as e:
            if addr.host in self.pending_outbound_connections:
                self.pending_outbound_connections.remove(addr.host)
            self.log.error(f"Exception in create outbound connections: {e}")
            self.log.error(f"Traceback: {traceback.format_exc()}")

    async def _connect_to_peers(self, random) -> None:
        next_feeler = self._poisson_next_send(time.time() * 1000 * 1000, 240, random)
        retry_introducers = False
        introducer_attempts: int = 0
        dns_server_index: int = 0
        local_peerinfo: Optional[PeerInfo] = await self.server.get_peer_info()
        last_timestamp_local_info: uint64 = uint64(int(time.time()))
        last_collision_timestamp = 0
        if self.initial_wait > 0:
            await asyncio.sleep(self.initial_wait)

        introducer_backoff = 1
        while not self.is_closed:
            try:
                assert self.address_manager is not None

                # We don't know any address, connect to the introducer to get some.
                size = await self.address_manager.size()
                if size == 0 or retry_introducers:
                    try:
                        await asyncio.sleep(introducer_backoff)
                    except asyncio.CancelledError:
                        return None
                    # Run dual between DNS servers and introducers. One time query DNS server,
                    # next two times query the introducer.
                    if introducer_attempts % 3 == 0 and len(self.dns_servers) > 0:
                        dns_address = self.dns_servers[dns_server_index]
                        dns_server_index = (dns_server_index + 1) % len(self.dns_servers)
                        await self._query_dns(dns_address)
                    else:
                        await self._introducer_client()
                        # there's some delay between receiving the peers from the
                        # introducer until they get incorporated to prevent this
                        # loop for running one more time. Add this delay to ensure
                        # that once we get peers, we stop contacting the introducer.
                        try:
                            await asyncio.sleep(5)
                        except asyncio.CancelledError:
                            return None

                    retry_introducers = False
                    introducer_attempts += 1
                    # keep doubling the introducer delay until we reach 5
                    # minutes
                    if introducer_backoff < 300:
                        introducer_backoff *= 2
                    continue
                else:
                    introducer_backoff = 1

                # Only connect out to one peer per network group (/16 for IPv4).
                groups = set()
                full_node_connected = self.server.get_full_node_outgoing_connections()
                connected = [c.get_peer_info() for c in full_node_connected]
                connected = [c for c in connected if c is not None]
                for conn in full_node_connected:
                    peer = conn.get_peer_info()
                    if peer is None:
                        continue
                    group = peer.get_group()
                    groups.add(group)

                # Feeler Connections
                #
                # Design goals:
                # * Increase the number of connectable addresses in the tried table.
                #
                # Method:
                # * Choose a random address from new and attempt to connect to it if we can connect
                # successfully it is added to tried.
                # * Start attempting feeler connections only after node finishes making outbound
                # connections.
                # * Only make a feeler connection once every few minutes.

                is_feeler = False
                has_collision = False
                if self._num_needed_peers() == 0:
                    if time.time() * 1000 * 1000 > next_feeler:
                        next_feeler = self._poisson_next_send(time.time() * 1000 * 1000, 240, random)
                        is_feeler = True

                await self.address_manager.resolve_tried_collisions()
                tries = 0
                now = time.time()
                got_peer = False
                addr: Optional[PeerInfo] = None
                max_tries = 50
                if len(groups) < 3:
                    max_tries = 10
                elif len(groups) <= 5:
                    max_tries = 25
                select_peer_interval = max(0.1, len(groups) * 0.25)
                while not got_peer and not self.is_closed:
                    self.log.debug(f"Address manager query count: {tries}. Query limit: {max_tries}")
                    try:
                        await asyncio.sleep(select_peer_interval)
                    except asyncio.CancelledError:
                        return None
                    tries += 1
                    if tries > max_tries:
                        addr = None
                        retry_introducers = True
                        break
                    info: Optional[ExtendedPeerInfo] = await self.address_manager.select_tried_collision()
                    if info is None or time.time() - last_collision_timestamp <= 60:
                        info = await self.address_manager.select_peer(is_feeler)
                    else:
                        has_collision = True
                        last_collision_timestamp = int(time.time())
                    if info is None:
                        if not is_feeler:
                            retry_introducers = True
                        break
                    # Require outbound connections, other than feelers,
                    # to be to distinct network groups.
                    addr = info.peer_info
                    if has_collision:
                        break
                    if addr is not None and not addr.is_valid():
                        addr = None
                        continue
                    if not is_feeler and addr.get_group() in groups:
                        addr = None
                        continue
                    if addr in connected:
                        addr = None
                        continue
                    # attempt a node once per 30 minutes.
                    if now - info.last_try < 1800:
                        continue
                    if time.time() - last_timestamp_local_info > 1800 or local_peerinfo is None:
                        local_peerinfo = await self.server.get_peer_info()
                        last_timestamp_local_info = uint64(int(time.time()))
                    if local_peerinfo is not None and addr == local_peerinfo:
                        continue
                    got_peer = True
                    self.log.debug(f"Addrman selected address: {addr}.")

                disconnect_after_handshake = is_feeler
                extra_peers_needed = self._num_needed_peers()
                if extra_peers_needed == 0:
                    disconnect_after_handshake = True
                    retry_introducers = False
                self.log.debug(f"Num peers needed: {extra_peers_needed}")
                initiate_connection = extra_peers_needed > 0 or has_collision or is_feeler
                connect_peer_interval = max(0.25, len(groups) * 0.5)
                if not initiate_connection:
                    connect_peer_interval += 15
                connect_peer_interval = min(connect_peer_interval, self.peer_connect_interval)
                if addr is not None and initiate_connection and addr.host not in self.pending_outbound_connections:
                    if len(self.pending_outbound_connections) >= MAX_CONCURRENT_OUTBOUND_CONNECTIONS:
                        self.log.debug("Max concurrent outbound connections reached. waiting")
                        await asyncio.wait(self.pending_tasks, return_when=asyncio.FIRST_COMPLETED)
                    self.pending_tasks.add(
                        asyncio.create_task(self.start_client_async(addr, disconnect_after_handshake))
                    )

                await asyncio.sleep(connect_peer_interval)

                # prune completed connect tasks
                self.pending_task = set(filter(lambda t: not t.done(), self.pending_tasks))

            except Exception as e:
                self.log.error(f"Exception in create outbound connections: {e}")
                self.log.error(f"Traceback: {traceback.format_exc()}")

    async def _periodically_serialize(self, random: Random):
        while not self.is_closed:
            if self.address_manager is None:
                await asyncio.sleep(10)
                continue
            serialize_interval = random.randint(15 * 60, 30 * 60)
            await asyncio.sleep(serialize_interval)
            async with self.address_manager.lock:
                await self.address_manager_store.serialize(self.address_manager)

    async def _periodically_cleanup(self) -> None:
        while not self.is_closed:
            # Removes entries with timestamp worse than 14 days ago
            # and with a high number of failed attempts.
            # Most likely, the peer left the network,
            # so we can save space in the peer tables.
            cleanup_interval = 1800
            max_timestamp_difference = 14 * 3600 * 24
            max_consecutive_failures = 10
            await asyncio.sleep(cleanup_interval)

            # Perform the cleanup only if we have at least 3 connections.
            full_node_connected = self.server.get_full_node_connections()
            connected = [c.get_peer_info() for c in full_node_connected]
            connected = [c for c in connected if c is not None]
            if self.address_manager is not None and len(connected) >= 3:
                async with self.address_manager.lock:
                    self.address_manager.cleanup(max_timestamp_difference, max_consecutive_failures)

    async def _respond_peers_common(self, request, peer_src, is_full_node) -> None:
        # Check if we got the peers from a full node or from the introducer.
        peers_adjusted_timestamp = []
        is_misbehaving = False
        if len(request.peer_list) > MAX_PEERS_RECEIVED_PER_REQUEST:
            is_misbehaving = True
        if is_full_node:
            if peer_src is None:
                return None
            async with self.lock:
                if peer_src.host not in self.received_count_from_peers:
                    self.received_count_from_peers[peer_src.host] = 0
                self.received_count_from_peers[peer_src.host] += len(request.peer_list)
                if self.received_count_from_peers[peer_src.host] > MAX_TOTAL_PEERS_RECEIVED:
                    is_misbehaving = True
        if is_misbehaving:
            return None
        for peer in request.peer_list:
            if peer.timestamp < 100000000 or peer.timestamp > time.time() + 10 * 60:
                # Invalid timestamp, predefine a bad one.
                current_peer = TimestampedPeerInfo(
                    peer.host,
                    peer.port,
                    uint64(int(time.time() - 5 * 24 * 60 * 60)),
                )
            else:
                current_peer = peer
            if not is_full_node:
                current_peer = TimestampedPeerInfo(
                    peer.host,
                    peer.port,
                    uint64(0),
                )
            peers_adjusted_timestamp.append(current_peer)

        assert self.address_manager is not None

        if is_full_node:
            await self.address_manager.add_to_new_table(peers_adjusted_timestamp, peer_src, 2 * 60 * 60)
        else:
            await self.address_manager.add_to_new_table(peers_adjusted_timestamp, None, 0)


class FullNodePeers(FullNodeDiscovery):
    self_advertise_task: Optional[asyncio.Task] = None
    address_relay_task: Optional[asyncio.Task] = None

    def __init__(
        self,
        server,
        root_path,
        max_inbound_count,
        target_outbound_count,
        peer_db_path,
        introducer_info,
        dns_servers,
        peer_connect_interval,
        selected_network,
        default_port,
        log,
    ):
        super().__init__(
            server,
            root_path,
            target_outbound_count,
            peer_db_path,
            introducer_info,
            dns_servers,
            peer_connect_interval,
            selected_network,
            default_port,
            log,
        )
        self.relay_queue = asyncio.Queue()
        self.neighbour_known_peers = {}
        self.key = randbits(256)

    async def start(self):
        await self.initialize_address_manager()
        self.self_advertise_task = asyncio.create_task(self._periodically_self_advertise_and_clean_data())
        self.address_relay_task = asyncio.create_task(self._address_relay())
        await self.start_tasks()

    async def close(self):
        await self._close_common()
        self.cancel_task_safe(self.self_advertise_task)
        self.cancel_task_safe(self.address_relay_task)

    async def _periodically_self_advertise_and_clean_data(self):
        while not self.is_closed:
            try:
                try:
                    await asyncio.sleep(24 * 3600)
                except asyncio.CancelledError:
                    return None
                # Clean up known nodes for neighbours every 24 hours.
                async with self.lock:
                    for neighbour in list(self.neighbour_known_peers.keys()):
                        self.neighbour_known_peers[neighbour].clear()
                # Self advertise every 24 hours.
                peer = await self.server.get_peer_info()
                if peer is None:
                    continue
                timestamped_peer = [
                    TimestampedPeerInfo(
                        peer.host,
                        peer.port,
                        uint64(int(time.time())),
                    )
                ]
                msg = make_msg(
                    ProtocolMessageTypes.respond_peers,
                    full_node_protocol.RespondPeers(timestamped_peer),
                )
                await self.server.send_to_all([msg], NodeType.FULL_NODE)

                async with self.lock:
                    for host in list(self.received_count_from_peers.keys()):
                        self.received_count_from_peers[host] = 0
            except Exception as e:
                self.log.error(f"Exception in self advertise: {e}")
                self.log.error(f"Traceback: {traceback.format_exc()}")

    async def add_peers_neighbour(self, peers, neighbour_info):
        neighbour_data = (neighbour_info.host, neighbour_info.port)
        async with self.lock:
            for peer in peers:
                if neighbour_data not in self.neighbour_known_peers:
                    self.neighbour_known_peers[neighbour_data] = set()
                if peer.host not in self.neighbour_known_peers[neighbour_data]:
                    self.neighbour_known_peers[neighbour_data].add(peer.host)

    async def request_peers(self, peer_info: PeerInfo):
        try:

            # Prevent a fingerprint attack: do not send peers to inbound connections.
            # This asymmetric behavior for inbound and outbound connections was introduced
            # to prevent a fingerprinting attack: an attacker can send specific fake addresses
            # to users' AddrMan and later request them by sending getaddr messages.
            # Making nodes which are behind NAT and can only make outgoing connections ignore
            # the request_peers message mitigates the attack.
            if self.address_manager is None:
                return None
            peers = await self.address_manager.get_peers()
            await self.add_peers_neighbour(peers, peer_info)

            msg = make_msg(
                ProtocolMessageTypes.respond_peers,
                full_node_protocol.RespondPeers(peers),
            )

            return msg
        except Exception as e:
            self.log.error(f"Request peers exception: {e}")

    async def respond_peers(self, request, peer_src, is_full_node):
        try:
            await self._respond_peers_common(request, peer_src, is_full_node)
            if is_full_node:
                await self.add_peers_neighbour(request.peer_list, peer_src)
                if len(request.peer_list) == 1 and self.relay_queue is not None:
                    peer = request.peer_list[0]
                    if peer.timestamp > time.time() - 60 * 10:
                        self.relay_queue.put_nowait((peer, 2))
        except Exception as e:
            self.log.error(f"Respond peers exception: {e}. Traceback: {traceback.format_exc()}")

    async def _address_relay(self):
        while not self.is_closed:
            try:
                try:
                    relay_peer, num_peers = await self.relay_queue.get()
                except asyncio.CancelledError:
                    return None
                relay_peer_info = PeerInfo(relay_peer.host, relay_peer.port)
                if not relay_peer_info.is_valid():
                    continue
                # https://en.bitcoin.it/wiki/Satoshi_Client_Node_Discovery#Address_Relay
                connections = self.server.get_full_node_connections()
                hashes = []
                cur_day = int(time.time()) // (24 * 60 * 60)
                for connection in connections:
                    peer_info = connection.get_peer_info()
                    if peer_info is None:
                        continue
                    cur_hash = int.from_bytes(
                        bytes(
                            std_hash(
                                self.key.to_bytes(32, byteorder="big")
                                + peer_info.get_key()
                                + cur_day.to_bytes(3, byteorder="big")
                            )
                        ),
                        byteorder="big",
                    )
                    hashes.append((cur_hash, connection))
                hashes.sort(key=lambda x: x[0])
                for index, (_, connection) in enumerate(hashes):
                    if index >= num_peers:
                        break
                    peer_info = connection.get_peer_info()
                    pair = (peer_info.host, peer_info.port)
                    async with self.lock:
                        if pair in self.neighbour_known_peers and relay_peer.host in self.neighbour_known_peers[pair]:
                            continue
                        if pair not in self.neighbour_known_peers:
                            self.neighbour_known_peers[pair] = set()
                        self.neighbour_known_peers[pair].add(relay_peer.host)
                    if connection.peer_node_id is None:
                        continue
                    msg = make_msg(
                        ProtocolMessageTypes.respond_peers,
                        full_node_protocol.RespondPeers([relay_peer]),
                    )
                    await connection.send_message(msg)
            except Exception as e:
                self.log.error(f"Exception in address relay: {e}")
                self.log.error(f"Traceback: {traceback.format_exc()}")


class WalletPeers(FullNodeDiscovery):
    def __init__(
        self,
        server,
        root_path,
        target_outbound_count,
        peer_db_path,
        introducer_info,
        dns_servers,
        peer_connect_interval,
        selected_network,
        default_port,
        log,
    ) -> None:
        super().__init__(
            server,
            root_path,
            target_outbound_count,
            peer_db_path,
            introducer_info,
            dns_servers,
            peer_connect_interval,
            selected_network,
            default_port,
            log,
        )

    async def start(self) -> None:
        self.initial_wait = 60
        await self.initialize_address_manager()
        await self.start_tasks()

    async def ensure_is_closed(self) -> None:
        if self.is_closed:
            return None
        await self._close_common()

    async def respond_peers(self, request, peer_src, is_full_node) -> None:
        await self._respond_peers_common(request, peer_src, is_full_node)
