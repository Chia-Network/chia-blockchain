import asyncio
import logging
import traceback
import time
import random
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import aiosqlite
import chia.server.ws_connection as ws
from chia.consensus.constants import ConsensusConstants
from chia.crawler.crawl_store import CrawlStore
from chia.crawler.peer_record import PeerRecord, PeerReliability
from chia.full_node.coin_store import CoinStore
from chia.protocols import full_node_protocol
from chia.server.server import ChiaServer
from chia.types.peer_info import PeerInfo
from chia.util.path import mkdir, path_from_root
from chia.util.ints import uint32, uint64

log = logging.getLogger(__name__)


bootstrap_peers = ["node.chia.net"]
minimum_height = 240000


class Crawler:
    sync_store: Any
    coin_store: CoinStore
    connection: aiosqlite.Connection
    config: Dict
    server: Any
    log: logging.Logger
    constants: ConsensusConstants
    _shut_down: bool
    root_path: Path
    peer_count: int
    peer_queue: asyncio.Queue
    with_peak: set

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
        self.server = None
        self._shut_down = False  # Set to true to close all infinite loops
        self.constants = consensus_constants
        self.state_changed_callback: Optional[Callable] = None
        self.crawl_store = None
        self.log = log
        self.peer_count = 0
        self.with_peak = set()
        self.peers_retrieved = []

        db_path_replaced: str = "crawler.db"
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def create_client(self, peer_info, on_connect):
        return await self.server.start_client(peer_info, on_connect)

    async def connect_task(self, peer):
        async def peer_action(peer: ws.WSChiaConnection):
            # Ask peer for peers
            response = await peer.request_peers(full_node_protocol.RequestPeers(), timeout=2)
            # Add peers to DB
            if isinstance(response, full_node_protocol.RespondPeers):
                self.peers_retrieved.append(response)
            peer_info = peer.get_peer_info()
            tries = 0
            while tries < 10:
                tries += 1
                if peer_info is None:
                    break
                if peer_info in self.with_peak:
                    break
                await asyncio.sleep(0.1)
            await peer.close()

        try:
            connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)
            if not connected:
                await self.crawl_store.peer_failed_to_connect(peer)
        except Exception as e:
            self.log.info(f"Exception: {e}. Traceback: {traceback.format_exc()}.")
            await self.crawl_store.peer_failed_to_connect(peer)

    async def process_peers(self):
        while True:
            peer = await self.peer_queue.get()
            await self.connect_task(peer)
            self.peer_queue.task_done()

    async def _start(self):
        self.task = asyncio.create_task(self.crawl())

    async def crawl(self):
        try:
            self.connection = await aiosqlite.connect(self.db_path)
            self.crawl_store = await CrawlStore.create(self.connection)
            self.log.info("Started")
            t_start = time.time()
            total_nodes = 0
            self.seen_nodes = set()
            tried_nodes = set()
            for peer in bootstrap_peers:
                new_peer = PeerRecord(peer, peer, 8444, False, 0, 0, 0, uint64(int(time.time())))
                new_peer_reliability = PeerReliability(peer)
                await self.crawl_store.add_peer(new_peer, new_peer_reliability)

            while True:
                self.with_peak = set()
                if random.randrange(0, 4) == 0:
                    await self.crawl_store.load_to_db()
                await self.crawl_store.load_reliable_peers_to_db()
                peers_to_crawl = await self.crawl_store.get_peers_to_crawl(10000, 100000)

                self.peer_queue = asyncio.Queue()
                for peer in peers_to_crawl:
                    if peer.port == 8444:
                        total_nodes += 1
                        if peer.ip_address not in tried_nodes:
                            tried_nodes.add(peer.ip_address)
                        self.peer_queue.put_nowait(peer)

                tasks = []
                for _ in range(250):
                    task = asyncio.create_task(self.process_peers())
                    tasks.append(task)
                await self.peer_queue.join()
                for task in tasks:
                    task.cancel()

                for response in self.peers_retrieved:
                    for response_peer in response.peer_list:
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
                            )
                            new_peer_reliability = PeerReliability(response_peer.host)
                            if self.crawl_store is not None:
                                await self.crawl_store.add_peer(new_peer, new_peer_reliability)
                self.peers_retrieved = []

                self.server.banned_peers = {}
                self.log.error("***")
                self.log.error("Finished batch:")
                self.log.error(f"Total connections attempted: {total_nodes}")
                self.log.error(f"Total unique nodes attempted: {len(tried_nodes)}.")
                t_now = time.time()
                t_delta = int(t_now - t_start)
                if t_delta > 0:
                    self.log.error(f"Avg connections per second: {total_nodes // t_delta}.")
                # Periodically print detailed stats.
                reliable_peers = self.crawl_store.get_reliable_peers()
                self.log.error(f"Reliable nodes: {reliable_peers}")
                banned_peers = self.crawl_store.get_banned_peers()
                self.log.error(f"Banned/ignored addresses: {banned_peers}")
                self.log.error("***")
        except Exception as e:
            self.log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    def set_server(self, server: ChiaServer):
        self.server = server

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    async def new_peak(self, request: full_node_protocol.NewPeak, peer: ws.WSChiaConnection):
        try:
            peer_info = peer.get_peer_info()
            if peer_info is None:
                return
            if request.height >= minimum_height:
                if self.crawl_store is not None:
                    await self.crawl_store.peer_connected_hostname(peer_info.host)
            self.with_peak.add(peer_info)
        except Exception as e:
            self.log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    async def on_connect(self, connection: ws.WSChiaConnection):
        pass

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        await self.connection.close()
