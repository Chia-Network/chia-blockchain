from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from chia.consensus.constants import ConsensusConstants
from chia.full_node.coin_store import CoinStore
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.seeder.crawl_store import CrawlStore
from chia.seeder.peer_record import PeerRecord, PeerReliability
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32, uint64
from chia.util.network import resolve
from chia.util.path import path_from_root

log = logging.getLogger(__name__)


class Crawler:
    sync_store: Any
    coin_store: CoinStore
    connection: Optional[aiosqlite.Connection]
    config: Dict
    _server: Optional[ChiaServer]
    crawl_store: Optional[CrawlStore]
    log: logging.Logger
    constants: ConsensusConstants
    _shut_down: bool
    root_path: Path
    peer_count: int
    with_peak: set
    minimum_version_count: int

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
    ):
        self.initialized = False
        self.root_path = root_path
        self.config = config
        self.connection = None
        self._server = None
        self._shut_down = False  # Set to true to close all infinite loops
        self.constants = consensus_constants
        self.state_changed_callback: Optional[StateChangedProtocol] = None
        self.crawl_store = None
        self.log = log
        self.peer_count = 0
        self.with_peak = set()
        self.peers_retrieved: List[Any] = []
        self.host_to_version: Dict[str, str] = {}
        self.version_cache: List[Tuple[str, str]] = []
        self.handshake_time: Dict[str, int] = {}
        self.best_timestamp_per_peer: Dict[str, int] = {}
        crawler_db_path: str = config.get("crawler_db_path", "crawler.db")
        self.db_path = path_from_root(root_path, crawler_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bootstrap_peers = config["bootstrap_peers"]
        self.minimum_height = config["minimum_height"]
        self.other_peers_port = config["other_peers_port"]
        self.versions: Dict[str, int] = defaultdict(lambda: 0)
        self.minimum_version_count = self.config.get("minimum_version_count", 100)
        if self.minimum_version_count < 1:
            self.log.warning(
                f"Crawler configuration minimum_version_count expected to be greater than zero: "
                f"{self.minimum_version_count!r}"
            )

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    async def create_client(self, peer_info, on_connect):
        return await self.server.start_client(peer_info, on_connect)

    async def connect_task(self, peer):
        async def peer_action(peer: WSChiaConnection):
            peer_info = peer.get_peer_info()
            version = peer.get_version()
            if peer_info is not None and version is not None:
                self.version_cache.append((peer_info.host, version))
            # Ask peer for peers
            response = await peer.call_api(FullNodeAPI.request_peers, full_node_protocol.RequestPeers(), timeout=3)
            # Add peers to DB
            if isinstance(response, full_node_protocol.RespondPeers):
                self.peers_retrieved.append(response)
            peer_info = peer.get_peer_info()
            tries = 0
            got_peak = False
            while tries < 25:
                tries += 1
                if peer_info is None:
                    break
                if peer_info in self.with_peak:
                    got_peak = True
                    break
                await asyncio.sleep(0.1)
            if not got_peak and peer_info is not None and self.crawl_store is not None:
                await self.crawl_store.peer_connected_hostname(peer_info.host, False)
            await peer.close()

        try:
            connected = await self.create_client(
                PeerInfo(await resolve(peer.ip_address, prefer_ipv6=self.config.get("prefer_ipv6", False)), peer.port),
                peer_action,
            )
            if not connected:
                await self.crawl_store.peer_failed_to_connect(peer)
        except Exception as e:
            self.log.info(f"Exception: {e}. Traceback: {traceback.format_exc()}.")
            await self.crawl_store.peer_failed_to_connect(peer)

    async def _start(self):
        # We override the default peer_connect_timeout when running from the crawler
        crawler_peer_timeout = self.config.get("peer_connect_timeout", 2)
        self.server.config["peer_connect_timeout"] = crawler_peer_timeout

        self.task = asyncio.create_task(self.crawl())

    async def crawl(self):
        # Ensure the state_changed callback is set up before moving on
        # Sometimes, the daemon connection + state changed callback isn't up and ready
        # by the time we get to the first _state_changed call, so this just ensures it's there before moving on
        while self.state_changed_callback is None:
            self.log.info("Waiting for state changed callback...")
            await asyncio.sleep(0.1)

        try:
            self.connection = await aiosqlite.connect(self.db_path)
            self.crawl_store = await CrawlStore.create(self.connection)
            self.log.info("Started")
            t_start = time.time()
            total_nodes = 0
            self.seen_nodes = set()
            tried_nodes = set()
            for peer in self.bootstrap_peers:
                new_peer = PeerRecord(
                    peer,
                    peer,
                    self.other_peers_port,
                    False,
                    0,
                    0,
                    0,
                    uint64(int(time.time())),
                    uint64(0),
                    "undefined",
                    uint64(0),
                    tls_version="unknown",
                )
                new_peer_reliability = PeerReliability(peer)
                self.crawl_store.maybe_add_peer(new_peer, new_peer_reliability)

            self.host_to_version, self.handshake_time = self.crawl_store.load_host_to_version()
            self.best_timestamp_per_peer = self.crawl_store.load_best_peer_reliability()
            self.versions = defaultdict(lambda: 0)
            for host, version in self.host_to_version.items():
                self.versions[version] += 1

            self._state_changed("loaded_initial_peers")

            while True:
                self.with_peak = set()
                peers_to_crawl = await self.crawl_store.get_peers_to_crawl(25000, 250000)
                tasks = set()
                for peer in peers_to_crawl:
                    if peer.port == self.other_peers_port:
                        total_nodes += 1
                        if peer.ip_address not in tried_nodes:
                            tried_nodes.add(peer.ip_address)
                        task = asyncio.create_task(self.connect_task(peer))
                        tasks.add(task)
                        if len(tasks) >= 250:
                            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        tasks = set(filter(lambda t: not t.done(), tasks))

                if len(tasks) > 0:
                    await asyncio.wait(tasks, timeout=30)

                for response in self.peers_retrieved:
                    for response_peer in response.peer_list:
                        if response_peer.host not in self.best_timestamp_per_peer:
                            self.best_timestamp_per_peer[response_peer.host] = response_peer.timestamp
                        self.best_timestamp_per_peer[response_peer.host] = max(
                            self.best_timestamp_per_peer[response_peer.host], response_peer.timestamp
                        )
                        if (
                            response_peer.host not in self.seen_nodes
                            and response_peer.timestamp > time.time() - 5 * 24 * 3600
                        ):
                            self.seen_nodes.add(response_peer.host)
                            new_peer = PeerRecord(
                                response_peer.host,
                                response_peer.host,
                                uint32(response_peer.port),
                                False,
                                uint64(0),
                                uint32(0),
                                uint64(0),
                                uint64(int(time.time())),
                                uint64(response_peer.timestamp),
                                "undefined",
                                uint64(0),
                                tls_version="unknown",
                            )
                            new_peer_reliability = PeerReliability(response_peer.host)
                            if self.crawl_store is not None:
                                self.crawl_store.maybe_add_peer(new_peer, new_peer_reliability)
                        await self.crawl_store.update_best_timestamp(
                            response_peer.host,
                            self.best_timestamp_per_peer[response_peer.host],
                        )
                for host, version in self.version_cache:
                    self.handshake_time[host] = int(time.time())
                    self.host_to_version[host] = version
                    await self.crawl_store.update_version(host, version, int(time.time()))

                to_remove = set()
                now = int(time.time())
                for host in self.host_to_version.keys():
                    active = True
                    if host not in self.handshake_time:
                        active = False
                    elif self.handshake_time[host] < now - 5 * 24 * 3600:
                        active = False
                    if not active:
                        to_remove.add(host)

                self.host_to_version = {
                    host: version for host, version in self.host_to_version.items() if host not in to_remove
                }
                self.best_timestamp_per_peer = {
                    host: timestamp
                    for host, timestamp in self.best_timestamp_per_peer.items()
                    if timestamp >= now - 5 * 24 * 3600
                }
                self.versions = defaultdict(lambda: 0)
                for host, version in self.host_to_version.items():
                    self.versions[version] += 1
                self.version_cache = []
                self.peers_retrieved = []

                self.server.banned_peers = {}
                if len(peers_to_crawl) == 0:
                    continue

                # Try up to 5 times to write to the DB in case there is a lock that causes a timeout
                for i in range(1, 5):
                    try:
                        await self.crawl_store.load_to_db()
                        await self.crawl_store.load_reliable_peers_to_db()
                    except Exception as e:
                        self.log.error(f"Exception while saving to DB: {e}.")
                        self.log.error("Waiting 5 seconds before retry...")
                        await asyncio.sleep(5)
                        continue
                    break
                total_records = self.crawl_store.get_total_records()
                ipv6_count = self.crawl_store.get_ipv6_peers()
                self.log.error("***")
                self.log.error("Finished batch:")
                self.log.error(f"Total IPs stored in DB: {total_records}.")
                self.log.error(f"Total IPV6 addresses stored in DB: {ipv6_count}")
                self.log.error(f"Total connections attempted since crawler started: {total_nodes}.")
                self.log.error(f"Total unique nodes attempted since crawler started: {len(tried_nodes)}.")
                t_now = time.time()
                t_delta = int(t_now - t_start)
                if t_delta > 0:
                    self.log.error(f"Avg connections per second: {total_nodes // t_delta}.")
                # Periodically print detailed stats.
                reliable_peers = self.crawl_store.get_reliable_peers()
                self.log.error(f"High quality reachable nodes, used by DNS introducer in replies: {reliable_peers}")
                banned_peers = self.crawl_store.get_banned_peers()
                ignored_peers = self.crawl_store.get_ignored_peers()
                available_peers = len(self.host_to_version)
                addresses_count = len(self.best_timestamp_per_peer)
                total_records = self.crawl_store.get_total_records()
                ipv6_addresses_count = 0
                for host in self.best_timestamp_per_peer.keys():
                    try:
                        ipaddress.IPv6Address(host)
                        ipv6_addresses_count += 1
                    except ipaddress.AddressValueError:
                        continue
                self.log.error(
                    "IPv4 addresses gossiped with timestamp in the last 5 days with respond_peers messages: "
                    f"{addresses_count - ipv6_addresses_count}."
                )
                self.log.error(
                    "IPv6 addresses gossiped with timestamp in the last 5 days with respond_peers messages: "
                    f"{ipv6_addresses_count}."
                )
                ipv6_available_peers = 0
                for host in self.host_to_version.keys():
                    try:
                        ipaddress.IPv6Address(host)
                        ipv6_available_peers += 1
                    except ipaddress.AddressValueError:
                        continue
                self.log.error(
                    f"Total IPv4 nodes reachable in the last 5 days: {available_peers - ipv6_available_peers}."
                )
                self.log.error(f"Total IPv6 nodes reachable in the last 5 days: {ipv6_available_peers}.")
                self.log.error("Version distribution among reachable in the last 5 days (at least 100 nodes):")
                for version, count in sorted(self.versions.items(), key=lambda kv: kv[1], reverse=True):
                    if count >= self.minimum_version_count:
                        self.log.error(f"Version: {version} - Count: {count}")
                self.log.error(f"Banned addresses in the DB: {banned_peers}")
                self.log.error(f"Temporary ignored addresses in the DB: {ignored_peers}")
                self.log.error(
                    "Peers to crawl from in the next batch (total IPs - ignored - banned): "
                    f"{total_records - banned_peers - ignored_peers}"
                )
                self.log.error("***")

                self._state_changed("crawl_batch_completed")
        except Exception as e:
            self.log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    def set_server(self, server: ChiaServer):
        self._server = server

    def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, change_data)

    async def new_peak(self, request: full_node_protocol.NewPeak, peer: WSChiaConnection):
        try:
            peer_info = peer.get_peer_info()
            tls_version = peer.get_tls_version()
            if tls_version is None:
                tls_version = "unknown"
            if peer_info is None:
                return
            if request.height >= self.minimum_height:
                if self.crawl_store is not None:
                    await self.crawl_store.peer_connected_hostname(peer_info.host, True, tls_version)
            self.with_peak.add(peer_info)
        except Exception as e:
            self.log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    async def on_connect(self, connection: WSChiaConnection):
        pass

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        if self.connection is not None:
            await self.connection.close()
