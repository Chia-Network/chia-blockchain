import asyncio
import logging
import ipaddress
import traceback
import random
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List

import aiosqlite
import src.server.ws_connection as ws
from src.consensus.constants import ConsensusConstants
from src.crawler.crawl_store import CrawlStore, utc_timestamp
from src.crawler.peer_record import PeerRecord, PeerReliability
from src.full_node.coin_store import CoinStore
from src.protocols import full_node_protocol, introducer_protocol
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from ipaddress import ip_address, IPv4Address
from src.util.path import mkdir, path_from_root

log = logging.getLogger(__name__)

try:
    from dnslib import *
except ImportError:
    print("Missing dependency dnslib: <https://pypi.python.org/pypi/dnslib>. Please install it with `pip`.")
    sys.exit(2)

# https://gist.github.com/pklaus/b5a7876d4d2cf7271873

class DomainName(str):
    def __getattr__(self, item):
        return DomainName(item + '.' + self)

D = DomainName('seeder.example.com.')
ns = DomainName('example.com.')
IP = '127.0.0.1'
TTL = 60 * 5
soa_record = SOA(
    mname=ns,  # primary name server
    rname=ns.hostmaster,  # email of the domain administrator
    times=(
        1619105223,  # serial number
        10800,  # refresh
        3600,  # retry
        604800,  # expire
        1800,  # minimum
    )
)
ns_records = [NS(ns)]

bootstrap_peers = ['node-eu.chia.net']
minimum_height = 100000


class EchoServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, callback):
        self.data_queue = asyncio.Queue(loop=asyncio.get_event_loop())
        self.callback = callback
        asyncio.ensure_future(self.respond())

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.ensure_future(self.handler(data, addr), loop=asyncio.get_event_loop())

    async def respond(self):
        while True:
            try:
                resp, caller = await self.data_queue.get()
                self.transport.sendto(resp, caller)
            except Exception as e:
                log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    async def handler(self, data, caller):
        try:
            data = await self.callback(data)
            if data is None:
                return
            await self.data_queue.put((data, caller))
        except Exception as e:
            log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

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
        self.log = log
        self.peer_count = 0

        db_path_replaced: str = "crawler.db"
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def dns_response(self, data):
        try:
            request = DNSRecord.parse(data)
            IPs = [MX(D.mail), soa_record] + ns_records
            # TODO: Balance for IPv4 and IPv6.
            peers = await self.crawl_store.get_cached_peers(16)
            if len(peers) == 0:
                return None
            for peer in peers:
                ipv4 = True
                try:
                    ip = ipaddress.IPv4Address(peer.host)
                except ValueError:
                    ipv4 = False
                if ipv4:
                    IPs.append(A(peer.host))
                else:
                    IPs.append(AAAA(peer.host))
            reply = DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=len(peers), ra=1), q=request.q)
            
            records = {
                D: IPs,
                D.ns1: [A(IP)],  # MX and NS records must never point to a CNAME alias (RFC 2181 section 10.3)
                D.ns2: [A(IP)],
                D.mail: [A(IP)],
                D.andrei: [CNAME(D)],
            }

            qname = request.q.qname
            qn = str(qname)
            qtype = request.q.qtype
            qt = QTYPE[qtype]
            if qn == D or qn.endswith('.' + D):
                for name, rrs in records.items():
                    if name == qn:
                        for rdata in rrs:
                            rqt = rdata.__class__.__name__
                            if qt in ['*', rqt]:
                                reply.add_answer(RR(rname=qname, rtype=getattr(QTYPE, rqt), rclass=1, ttl=TTL, rdata=rdata))

                for rdata in ns_records:
                    reply.add_ar(RR(rname=D, rtype=QTYPE.NS, rclass=1, ttl=TTL, rdata=rdata))

                reply.add_auth(RR(rname=D, rtype=QTYPE.SOA, rclass=1, ttl=TTL, rdata=soa_record))

            return reply.pack()
        except Exception as e:
            self.log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    async def _start(self):
        asyncio.create_task(self.crawl())
        # Get a reference to the event loop as we plan to use
        # low-level APIs.
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all
        # client requests.
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: EchoServerProtocol(self.dns_response),
            local_addr=('0.0.0.0', 53)
        )

    async def create_client(self, peer_info, on_connect):
        return await self.server.start_client(peer_info, on_connect)

    async def crawl(self):
        try:
            self.connection = await aiosqlite.connect(self.db_path)
            self.crawl_store = await CrawlStore.create(self.connection)
            self.log.info("Started")
            t_start = time.time()
            self.peer_count = 0
            total_nodes = 0
            self.seen_nodes = set()
            tried_nodes = set()
            for peer in bootstrap_peers:
                new_peer = PeerRecord(peer, peer, 8444, False, 0, 0, 0, utc_timestamp())
                new_peer_reliability = PeerReliability(peer)
                await self.crawl_store.add_peer(new_peer, new_peer_reliability)

            while True:
                await asyncio.sleep(2)
                async def introducer_action(peer: ws.WSChiaConnection):
                    # Ask introducer for peers
                    response = await peer.request_peers_introducer(introducer_protocol.RequestPeersIntroducer())
                    # Add peers to DB
                    if isinstance(response, introducer_protocol.RespondPeersIntroducer):
                        # self.log.error(f"Introduced sent us {len(response.peer_list)} peers")
                        for response_peer in response.peer_list:
                            current = await self.crawl_store.get_peer_by_ip(response_peer.host)
                            if current is None:
                                new_peer = PeerRecord(response_peer.host, response_peer.host, response_peer.port,
                                                    False, 0, 0, 0, utc_timestamp())
                                # self.log.info(f"Adding {new_peer.ip_address}")
                                new_peer_reliability = PeerReliability(response_peer.host)
                                await self.crawl_store.add_peer(new_peer, new_peer_reliability)
                    self.peer_count += len(response.peer_list)
                    self.log.error(f"Peer count: {self.peer_count}.")
                    # disconnect
                    await peer.close()

                if self.peer_count == 0:
                    await self.create_client(self.introducer_info, introducer_action)
                # not_connected_peers: List[PeerRecord] = await self.crawl_store.get_peers_today_not_connected()
                # Periodically reload cached peers.
                if random.randrange(0, 4) == 0:
                    await self.crawl_store.reload_cached_peers()
                peers_to_crawl = await self.crawl_store.get_peers_to_crawl(10000)
                # connected_peers: List[PeerRecord] = await self.crawl_store.get_peers_today_connected()
                # good_peers = await self.crawl_store.get_cached_peers(99999999)

                async def peer_action(peer: ws.WSChiaConnection):
                    # Ask peer for peers
                    response = await peer.request_peers(full_node_protocol.RequestPeers(), timeout=3)
                    # Add peers to DB
                    if isinstance(response, full_node_protocol.RespondPeers):
                        # self.log.error(f"{peer.peer_host} sent us {len(response.peer_list)}")
                        for response_peer in response.peer_list:
                            # current = await self.crawl_store.get_peer_by_ip(response_peer.host)
                            if response_peer.host not in self.seen_nodes and response_peer.timestamp > time.time() - 5 * 24 * 3600:
                                self.seen_nodes.add(response_peer.host)
                                new_peer = PeerRecord(response_peer.host, response_peer.host, response_peer.port,
                                                    False, 0, 0, 0, utc_timestamp())
                                # self.log.info(f"Adding {new_peer.ip_address}")
                                new_peer_reliability = PeerReliability(response_peer.host)
                                await self.crawl_store.add_peer(new_peer, new_peer_reliability)

                    await asyncio.sleep(1)
                    await peer.close()

                tasks = []
                async def connect_task(self, peer):
                    try:
                        now = utc_timestamp()
                        connected = False
                        """if peer.try_count == 0:
                            connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)
                        elif peer.try_count > 0 and peer.try_count < 24 and peer.last_try_timestamp - 3600 > now:
                            connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)
                        elif peer.last_try_timestamp - 3600 * 24 > now:
                            connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)
                        """
                        connected = await self.create_client(PeerInfo(peer.ip_address, peer.port), peer_action)
                        if not connected:
                            await self.crawl_store.peer_tried_to_connect(peer)
                    except Exception as e:
                        self.log.info(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

                start = 0

                def batch(iterable, n=1):
                    l = len(iterable)
                    for ndx in range(0, l, n):
                        yield iterable[ndx:min(ndx + n, l)]

                batch_count = 0
                for peers in batch(peers_to_crawl, 500):
                    self.log.info(f"Starting batch {batch_count*100}-{batch_count*100+100}")
                    batch_count += 1
                    tasks = []
                    for peer in peers:
                        if peer.port == 8444:
                            task = asyncio.create_task(connect_task(self, peer))
                            tasks.append(task)
                            total_nodes += 1
                            if peer.ip_address not in tried_nodes:
                                tried_nodes.add(peer.ip_address)
                    if len(tasks) > 0:
                        await asyncio.wait(tasks)
                    # stat_not_connected_peers: List[PeerRecord] = await self.crawl_store.get_peers_today_not_connected()
                    # stat_connected_peers: List[PeerRecord] = await self.crawl_store.get_peers_today_connected()
                    # self.log.info(f"Current not_connected_peers count = {len(stat_not_connected_peers)}")
                    # self.log.info(f"Current connected_peers count = {len(stat_connected_peers)}")

                self.server.banned_peers = {}
                self.log.error("***")
                self.log.error(f"Finished batch:")
                self.log.error(f"Total connections attempted: {total_nodes}")
                self.log.error(f"Total unique nodes attempted: {len(tried_nodes)}.")
                t_now = time.time()
                t_delta = int(t_now - t_start)
                self.log.error(f"Avg connections per second: {total_nodes // t_delta}.")
                # Periodically print detailed stats.
                good_peers = await self.crawl_store.get_cached_peers(99999999)
                self.log.error(f"Reliable nodes: {len(good_peers)}")
                if random.randrange(0, 10) == 0:
                    num_connected_today = await self.crawl_store.get_peers_today_connected()
                    self.log.error(f"Peers reachable today: {num_connected_today}.")
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
            if request.height >= minimum_height:
                peer_info = peer.get_peer_info()
                if peer_info is not None:
                    await self.crawl_store.peer_connected_hostname(peer_info.host)
        except Exception as e:
            self.log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    async def on_connect(self, connection: ws.WSChiaConnection):
        pass

    def _close(self):
        self._shut_down = True
        self.transport.close()

    async def _await_closed(self):
        await self.connection.close()
