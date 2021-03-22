import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List

import aiosqlite

import src.server.ws_connection as ws
from src.consensus.constants import ConsensusConstants
from src.crawler.crawl_store import CrawlStore, utc_timestamp
from src.crawler.peer_record import PeerRecord
from src.full_node.coin_store import CoinStore
from src.protocols import full_node_protocol, introducer_protocol
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo

from src.util.path import mkdir, path_from_root


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
        self.introducer_info = PeerInfo(self.config["introducer_peer"]["host"], self.config["introducer_peer"]["port"])
        self.crawl_store = None
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        db_path_replaced: str = "crawler.db"
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def _start(self):
        asyncio.create_task(self.crawl())

    async def create_client(self, peer_info, on_connect):
        return await self.server.start_client(peer_info, on_connect)

    async def crawl(self):
        self.connection = await aiosqlite.connect(self.db_path)
        self.crawl_store = await CrawlStore.create(self.connection)
        while True:
            print("Started")
            await asyncio.sleep(1)
            async def introducer_action(peer: ws.WSChiaConnection):
                # Ask introducer for peers
                response = await peer.request_peers_introducer(introducer_protocol.RequestPeersIntroducer())
                # Add peers to DB
                if isinstance(response, introducer_protocol.RespondPeersIntroducer):
                    for response_peer in response.peer_list:
                        current = await self.crawl_store.get_peer_by_ip(response_peer.host)
                        if current is None:
                            new_peer = PeerRecord(response_peer.host, response_peer.host, response_peer.port,
                                                  False, 0, 0, 0, 0)
                            await self.crawl_store.add_peer(new_peer)
                # disconnect
                await peer.close()

            await self.create_client(self.introducer_info, introducer_action)
            not_connected_peers: List[PeerRecord] = await self.crawl_store.get_peers_today_not_connected()
            connected_peers: List[PeerRecord] = await self.crawl_store.get_peers_today_connected()

            async def peer_action(peer: ws.WSChiaConnection):
                # Ask peer for peers
                response = await peer.request_peers(full_node_protocol.RequestPeers())
                # Add peers to DB
                if isinstance(response, full_node_protocol.RespondPeers):
                    for response_peer in response.peer_list:
                        current = await self.crawl_store.get_peer_by_ip(response_peer.host)
                        if current is None:
                            new_peer = PeerRecord(peer.peer_node_id.hex(), response_peer.peer.host, response_peer.port,
                                                  False, 0, 0, 0, 0)
                            self.crawl_store.add_peer(new_peer)

                await peer.close()

            self.log.info(f"Current not_connected_peers count = {len(not_connected_peers)}")
            self.log.info(f"Current connected_peers count = {len(connected_peers)}")

            for peer in not_connected_peers:
                now = utc_timestamp()
                if peer.try_count == 0:
                    connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)
                elif peer.try_count > 0 and peer.try_count < 24 and peer.last_try_timestamp - 3600 > now:
                    connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)
                elif peer.last_try_timestamp - 3600 * 24 > now:
                    connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)

            self.server.banned_peers = {}

    def set_server(self, server: ChiaServer):
        self.server = server

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    async def new_peak(self, request: full_node_protocol.NewPeak, peer: ws.WSChiaConnection):
        pass

    async def on_connect(self, connection: ws.WSChiaConnection):
        pass

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        await self.connection.close()
