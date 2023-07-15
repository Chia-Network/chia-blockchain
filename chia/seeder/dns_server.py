from __future__ import annotations

import asyncio
import logging
import signal
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

import aiosqlite
from dnslib import AAAA, NS, QTYPE, RCODE, RD, RR, SOA, A, DNSError, DNSHeader, DNSQuestion, DNSRecord

from chia.seeder.crawl_store import CrawlStore
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root

SERVICE_NAME = "seeder"
log = logging.getLogger(__name__)


# DNS snippet taken from: https://gist.github.com/pklaus/b5a7876d4d2cf7271873


class DomainName(str):
    def __getattr__(self, item: str) -> DomainName:
        return DomainName(item + "." + self)  # DomainName.NS becomes DomainName("NS.DomainName")


class EchoServerProtocol(asyncio.DatagramProtocol):
    transport: asyncio.DatagramTransport
    data_queue: asyncio.Queue[tuple[DNSRecord, tuple[str, int]]]
    callback: Callable[[DNSRecord], Awaitable[Optional[DNSRecord]]]

    def __init__(self, callback: Callable[[DNSRecord], Awaitable[Optional[DNSRecord]]]) -> None:
        self.data_queue = asyncio.Queue()
        self.callback = callback
        asyncio.ensure_future(self.respond())

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        # we use the #ignore because transport is a subclass of BaseTransport, but we need the real type.
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            dns_request: DNSRecord = DNSRecord.parse(data)  # it's better to parse here, so we have a real type.
        except DNSError as e:
            log.warning(f"Received invalid DNS request: {e}")
            return
        except Exception as e:
            log.error(f"Exception when receiving a datagram: {e}. Traceback: {traceback.format_exc()}.")
            return
        asyncio.ensure_future(self.handler(dns_request, addr))

    async def respond(self) -> None:
        while True:
            try:
                reply, caller = await self.data_queue.get()
                self.transport.sendto(reply.pack(), caller)
            except Exception as e:
                log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    async def handler(self, data: DNSRecord, caller: tuple[str, int]) -> None:
        try:
            data = await self.callback(data)
            if data is None:
                return
            await self.data_queue.put((data, caller))
        except Exception as e:
            log.error(f"Exception during DNS record processing: {e}. Traceback: {traceback.format_exc()}.")


@dataclass(frozen=True)
class PeerList:
    ipv4: List[IPv4Address]
    ipv6: List[IPv6Address]

    @property
    def no_peers(self) -> bool:
        return not self.ipv4 and not self.ipv6


@dataclass
class DNSServer:
    config: Dict[str, Any]
    root_path: Path
    lock: asyncio.Lock = asyncio.Lock()
    shutdown_event: asyncio.Event = asyncio.Event()
    db_connection: aiosqlite.Connection = field(init=False)
    crawl_store: CrawlStore = field(init=False)
    reliable_task: asyncio.Task[None] = field(init=False)
    transport: asyncio.DatagramTransport = field(init=False)
    protocol: EchoServerProtocol = field(init=False)
    dns_port: int = field(init=False)
    db_path: Path = field(init=False)
    domain: DomainName = field(init=False)
    ns1: DomainName = field(init=False)
    ns2: Optional[DomainName] = field(init=False)
    ns_records: List[RR] = field(init=False)
    ttl: int = field(init=False)
    soa_record: RR = field(init=False)
    reliable_peers_v4: List[IPv4Address] = field(default_factory=list)
    reliable_peers_v6: List[IPv6Address] = field(default_factory=list)
    pointer_v4: int = 0
    pointer_v6: int = 0

    def __post_init__(self) -> None:
        """
        We initialize all the variables set to field(init=False) here.
        """
        # From Config
        self.dns_port: int = self.config.get("dns_port", 53)
        # DB Path
        crawler_db_path: str = self.config.get("crawler_db_path", "crawler.db")
        self.db_path: Path = path_from_root(self.root_path, crawler_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # DNS info
        self.domain: DomainName = DomainName(self.config["domain_name"])
        self.ns1: DomainName = DomainName(self.config["nameserver"])
        self.ns2: Optional[DomainName] = (
            DomainName(self.config["nameserver2"]) if self.config.get("nameserver2") else None
        )
        self.ns_records: List[NS] = [NS(self.ns1), NS(self.ns2)] if self.ns2 else [NS(self.ns1)]
        self.ttl: int = self.config["ttl"]
        self.soa_record: SOA = SOA(
            mname=self.ns1,  # primary name server
            rname=self.config["soa"]["rname"],  # email of the domain administrator
            times=(
                self.config["soa"]["serial_number"],
                self.config["soa"]["refresh"],
                self.config["soa"]["retry"],
                self.config["soa"]["expire"],
                self.config["soa"]["minimum"],
            ),
        )

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        await self.setup_signal_handlers()
        self.db_connection = await aiosqlite.connect(self.db_path, timeout=60)
        self.crawl_store = CrawlStore(self.db_connection)
        # Get a reference to the event loop as we plan to use
        # low-level APIs.
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all
        # client requests.
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: EchoServerProtocol(self.dns_response), local_addr=("::0", self.dns_port)
        )
        self.reliable_task = asyncio.create_task(self.periodically_get_reliable_peers())
        try:
            yield
        finally:  # catches any errors and properly shuts down the server
            if not self.shutdown_event.is_set():
                await self.stop()

    async def setup_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, self._accept_signal)
            loop.add_signal_handler(signal.SIGTERM, self._accept_signal)
        except NotImplementedError:
            log.info("signal handlers unsupported on this platform")

    def _accept_signal(self) -> None:
        asyncio.create_task(self.stop())

    async def stop(self) -> None:
        self.reliable_task.cancel()  # cancel the task
        await self.db_connection.close()
        self.transport.close()
        self.shutdown_event.set()

    async def periodically_get_reliable_peers(self) -> None:
        sleep_interval = 0
        while not self.shutdown_event.is_set():
            new_reliable_peers = []
            try:
                new_reliable_peers = await self.crawl_store.get_good_peers()
            except Exception as e:
                log.error(f"Error loading reliable peers from database: {e}. TracebacK: {traceback.format_exc()}.")
            if len(new_reliable_peers) == 0:
                await asyncio.sleep(60)  # sleep for 1 minute, because the crawler has not yet started
                continue
            async with self.lock:
                self.reliable_peers_v4 = []
                self.reliable_peers_v6 = []
                self.pointer_v4 = 0
                self.pointer_v6 = 0
                for peer in new_reliable_peers:
                    ipv4_peer = None
                    try:
                        ipv4_peer = IPv4Address(peer)
                    except ValueError:
                        pass
                    if ipv4_peer is not None:
                        self.reliable_peers_v4.append(ipv4_peer)
                    else:
                        try:
                            ipv6_peer = IPv6Address(peer)
                        except ValueError:
                            log.error(f"Invalid peer: {peer}")
                            continue
                        self.reliable_peers_v6.append(ipv6_peer)
                log.error(
                    f"Number of reliable peers discovered in dns server:"
                    f" IPv4 count - {len(self.reliable_peers_v4)}"
                    f" IPv6 count - {len(self.reliable_peers_v6)}"
                )
            sleep_interval = min(15, sleep_interval + 1)
            await asyncio.sleep(sleep_interval * 60)

    async def get_peers_to_respond(self, ipv4_count: int, ipv6_count: int) -> PeerList:
        async with self.lock:
            # Append IPv4.
            ipv4_peers: List[IPv4Address] = []
            size = len(self.reliable_peers_v4)
            if ipv4_count > 0 and size <= ipv4_count:
                ipv4_peers = self.reliable_peers_v4
            elif ipv4_count > 0:
                ipv4_peers = [
                    self.reliable_peers_v4[i % size] for i in range(self.pointer_v4, self.pointer_v4 + ipv4_count)
                ]
                self.pointer_v4 = (self.pointer_v4 + ipv4_count) % size  # mark where we left off
            # Append IPv6.
            ipv6_peers: List[IPv6Address] = []
            size = len(self.reliable_peers_v6)
            if ipv6_count > 0 and size <= ipv6_count:
                ipv6_peers = self.reliable_peers_v6
            elif ipv6_count > 0:
                ipv6_peers = [
                    self.reliable_peers_v6[i % size] for i in range(self.pointer_v6, self.pointer_v6 + ipv6_count)
                ]
                self.pointer_v6 = (self.pointer_v6 + ipv6_count) % size  # mark where we left off
            return PeerList(ipv4_peers, ipv6_peers)

    async def dns_response(self, request: DNSRecord) -> DNSRecord:
        """
        This function is called when a DNS request is received, and it returns a DNS response.
        It does not catch any errors as it is called from within a try-except block.
        """
        # QR means query response, AA means authoritative answer, RA means recursion available
        reply = DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=1, ra=0), q=request.q)
        ttl: int = self.ttl
        ips: List[RD] = []
        ipv4_count = 0
        ipv6_count = 0
        dns_question: DNSQuestion = request.q  # this is the question / request
        question_type: int = dns_question.qtype  # the type of the record being requested
        if question_type is QTYPE.A:
            ipv4_count = 32
        elif question_type is QTYPE.AAAA:
            ipv6_count = 32
        elif question_type is QTYPE.ANY:
            ipv4_count = 16
            ipv6_count = 16
        else:
            ipv4_count = 32
        peers: PeerList = await self.get_peers_to_respond(ipv4_count, ipv6_count)
        if peers.no_peers:
            log.error("No peers found, returning SOA and NS records only.")
            ttl = 60  # 1 minute as we should have some peers very soon
        # we always return the SOA and NS records, so we continue even if there are no peers
        ips.extend([A(peer) for peer in peers.ipv4])
        ips.extend([AAAA(peer) for peer in peers.ipv6])

        records: Dict[DomainName, List[RD]] = {  # this is where we can add other records we want to serve
            self.domain: ips,
        }

        qname = dns_question.qname  # the name being queried / requested
        # DNS labels are mixed case with DNS resolvers that implement the use of bit 0x20 to improve
        # transaction identity. See https://datatracker.ietf.org/doc/html/draft-vixie-dnsext-dns0x20-00
        qname_str = str(qname).lower()
        if qname_str == self.domain or qname_str.endswith("." + self.domain):  # if the seeder domain
            for domain_name, domain_responses in records.items():
                if domain_name == qname_str:  # if the dns name is the same as the requested name
                    for response in domain_responses:
                        rqt: int = getattr(QTYPE, response.__class__.__name__)
                        if question_type == rqt or (
                            question_type == RCODE.ANY and (rqt == RCODE.A or rqt == RCODE.AAAA)
                        ):
                            reply.add_answer(RR(rname=qname, rtype=rqt, rclass=1, ttl=ttl, rdata=response))
            if len(reply.rr) == 0:  # if we didn't find any records to return
                reply.header.rcode = RCODE.NXDOMAIN
            # always put nameservers and the SOA records
            for nameserver in self.ns_records:
                reply.add_auth(RR(rname=self.domain, rtype=QTYPE.NS, rclass=1, ttl=ttl, rdata=nameserver))
            reply.add_auth(RR(rname=self.domain, rtype=QTYPE.SOA, rclass=1, ttl=ttl, rdata=self.soa_record))
        else:  # we don't answer for other domains (we have the not recursive bit set)
            reply.header.rcode = RCODE.REFUSED
        return reply


async def run_dns_server(dns_server: DNSServer) -> None:
    async with dns_server.run():
        await dns_server.shutdown_event.wait()  # this is released on SIGINT or SIGTERM or any unhandled exception


def create_dns_server_service(config: Dict[str, Any], root_path: Path) -> DNSServer:
    return DNSServer(config, root_path)


def main() -> None:
    root_path = DEFAULT_ROOT_PATH
    config = load_config(root_path, "config.yaml", SERVICE_NAME)
    initialize_service_logging(service_name=SERVICE_NAME, config=config)
    dns_server = create_dns_server_service(config, root_path)
    asyncio.run(run_dns_server(dns_server))


if __name__ == "__main__":
    main()
