from __future__ import annotations

import asyncio
import logging
import signal
import sys
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address, ip_address
from multiprocessing import freeze_support
from pathlib import Path
from types import FrameType
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

import aiosqlite
from dnslib import AAAA, EDNS0, NS, QTYPE, RCODE, RD, RR, SOA, A, DNSError, DNSHeader, DNSQuestion, DNSRecord

from chia.seeder.crawl_store import CrawlStore
from chia.server.signal_handlers import SignalHandlers
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root

SERVICE_NAME = "seeder"
log = logging.getLogger(__name__)
DnsCallback = Callable[[DNSRecord], Awaitable[DNSRecord]]


# DNS snippet taken from: https://gist.github.com/pklaus/b5a7876d4d2cf7271873


class DomainName(str):
    def __getattr__(self, item: str) -> DomainName:
        return DomainName(f"{item}.{self}")  # DomainName.NS becomes DomainName("NS.DomainName")


@dataclass(frozen=True)
class PeerList:
    ipv4: List[IPv4Address]
    ipv6: List[IPv6Address]

    @property
    def no_peers(self) -> bool:
        return not self.ipv4 and not self.ipv6


@dataclass
class UDPDNSServerProtocol(asyncio.DatagramProtocol):
    """
    This is a really simple UDP Server, that converts all requests to DNSRecord objects and passes them to the callback.
    """

    callback: DnsCallback
    transport: Optional[asyncio.DatagramTransport] = field(init=False, default=None)
    data_queue: asyncio.Queue[tuple[DNSRecord, tuple[str, int]]] = field(default_factory=asyncio.Queue)
    queue_task: Optional[asyncio.Task[None]] = field(init=False, default=None)

    def start(self) -> None:
        self.queue_task = asyncio.create_task(self.respond())  # This starts the dns respond loop.

    async def stop(self) -> None:
        if self.queue_task is not None:
            self.queue_task.cancel()
            try:
                await self.queue_task
            except asyncio.CancelledError:  # we dont care
                pass
        if self.transport is not None:
            self.transport.close()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        # we use the #ignore because transport is a subclass of BaseTransport, but we need the real type.
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        log.debug(f"Received UDP DNS request from {addr}.")
        dns_request: Optional[DNSRecord] = parse_dns_request(data)
        if dns_request is None:  # Invalid Request, we can just drop it and move on.
            return
        asyncio.create_task(self.handler(dns_request, addr))

    async def respond(self) -> None:
        log.info("UDP DNS responder started.")
        while self.transport is None:  # we wait for the transport to be set.
            await asyncio.sleep(0.1)
        while not self.transport.is_closing():
            try:
                edns_max_size = 0
                reply, caller = await self.data_queue.get()
                if len(reply.ar) > 0 and reply.ar[0].rtype == QTYPE.OPT:
                    edns_max_size = reply.ar[0].edns_len

                reply_packed = reply.pack()

                if len(reply_packed) > max(512, edns_max_size):  # 512 is the default max size for DNS:
                    log.debug(f"DNS response to {caller} is too large, truncating.")
                    reply_packed = reply.truncate().pack()

                self.transport.sendto(reply_packed, caller)
                log.debug(f"Sent UDP DNS response to {caller}, of size {len(reply_packed)}.")
            except Exception as e:
                log.error(f"Exception while responding to UDP DNS request: {e}. Traceback: {traceback.format_exc()}.")
        log.info("UDP DNS responder stopped.")

    async def handler(self, data: DNSRecord, caller: tuple[str, int]) -> None:
        r_data = await get_dns_reply(self.callback, data)  # process the request, returning a DNSRecord response.
        await self.data_queue.put((r_data, caller))


@dataclass
class TCPDNSServerProtocol(asyncio.BufferedProtocol):
    """
    This TCP server is a little more complicated, because we need to handle the length field, however it still
    converts all requests to DNSRecord objects and passes them to the callback, after receiving the full message.
    """

    callback: DnsCallback
    transport: Optional[asyncio.Transport] = field(init=False, default=None)
    peer_info: str = field(init=False, default="")
    expected_length: int = 0
    buffer: bytearray = field(init=False, default_factory=lambda: bytearray(2))
    futures: List[asyncio.Future[None]] = field(init=False, default_factory=list)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """
        This is called whenever we get a new connection.
        """
        # we use the #ignore because transport is a subclass of BaseTransport, but we need the real type.
        self.transport = transport  # type: ignore[assignment]
        peer_info = transport.get_extra_info("peername")
        self.peer_info = f"{peer_info[0]}:{peer_info[1]}"
        log.debug(f"TCP connection established with {self.peer_info}.")

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """
        This is called whenever a connection is lost, or closed.
        """
        if exc is not None:
            log.debug(f"TCP DNS connection lost with {self.peer_info}. Exception: {exc}.")
        else:
            log.debug(f"TCP DNS connection closed with {self.peer_info}.")
        # reset the state of the protocol.
        for future in self.futures:
            future.cancel()
        self.futures = []
        self.buffer = bytearray(2)
        self.expected_length = 0

    def get_buffer(self, sizehint: int) -> memoryview:
        """
        This is the first function called after connection_made, it returns a buffer that the tcp server will write to.
        Once a buffer is written to, buffer_updated is called.
        """
        return memoryview(self.buffer)

    def buffer_updated(self, nbytes: int) -> None:
        """
        This is called whenever the buffer is written to, and it loops through the buffer, grouping them into messages
        and then dns records.
        """
        while not len(self.buffer) == 0 and self.transport is not None:
            if not self.expected_length:
                # Length field received (This is the first part of the message)
                self.expected_length = int.from_bytes(self.buffer, byteorder="big")
                self.buffer = self.buffer[2:]  # Remove the length field from the buffer.

            if len(self.buffer) >= self.expected_length:
                # This is the rest of the message (after the length field)
                message = self.buffer[: self.expected_length]
                self.buffer = self.buffer[self.expected_length :]  # Remove the message from the buffer
                self.expected_length = 0  # Reset the expected length

                dns_request: Optional[DNSRecord] = parse_dns_request(message)
                if dns_request is None:  # Invalid Request, so we disconnect and don't send anything back.
                    self.transport.close()
                    return
                self.futures.append(asyncio.create_task(self.handle_and_respond(dns_request)))

        self.buffer = bytearray(2 if self.expected_length == 0 else self.expected_length)  # Reset the buffer if empty.

    def eof_received(self) -> Optional[bool]:
        """
        This is called when the client closes the connection, False or None means we close the connection.
        True means we keep the connection open.
        """
        if len(self.futures) > 0:  # Successful requests
            if self.expected_length != 0:  # Incomplete requests
                log.warning(
                    f"Received incomplete TCP DNS request of length {self.expected_length} from {self.peer_info}, "
                    f"closing connection after dns replies are sent."
                )
            asyncio.create_task(self.wait_for_futures())
            return True  # Keep connection open, until the futures are done.
        log.info(f"Received early EOF from {self.peer_info}, closing connection.")
        return False

    async def wait_for_futures(self) -> None:
        """
        Waits for all the futures to complete, and then closes the connection.
        """
        try:
            await asyncio.wait_for(asyncio.gather(*self.futures), timeout=10)
        except asyncio.TimeoutError:
            log.warning(f"Timed out waiting for DNS replies to be sent to {self.peer_info}.")
        if self.transport is not None:
            self.transport.close()

    async def handle_and_respond(self, data: DNSRecord) -> None:
        r_data = await get_dns_reply(self.callback, data)  # process the request, returning a DNSRecord response.
        try:
            # If the client closed the connection, we don't want to send anything.
            if self.transport is not None and not self.transport.is_closing():
                self.transport.write(dns_response_to_tcp(r_data))  # send data back to the client
            log.debug(f"Sent DNS response for {data.q.qname}, to {self.peer_info}.")
        except Exception as e:
            log.error(f"Exception while responding to TCP DNS request: {e}. Traceback: {traceback.format_exc()}.")


def dns_response_to_tcp(data: DNSRecord) -> bytes:
    """
    Converts a DNSRecord response to a TCP DNS response, by adding a 2 byte length field to the start.
    """
    dns_response = data.pack()
    dns_response_length = len(dns_response).to_bytes(2, byteorder="big")
    return bytes(dns_response_length + dns_response)


def create_dns_reply(dns_request: DNSRecord) -> DNSRecord:
    """
    Creates a DNS response with the correct header and section flags set.
    """
    # QR means query response, AA means authoritative answer, RA means recursion available
    return DNSRecord(DNSHeader(id=dns_request.header.id, qr=1, aa=1, ra=0), q=dns_request.q)


def parse_dns_request(data: bytes) -> Optional[DNSRecord]:
    """
    Parses the DNS request, and returns a DNSRecord object, or None if the request is invalid.
    """
    dns_request: Optional[DNSRecord] = None
    try:
        dns_request = DNSRecord.parse(data)
    except DNSError as e:
        log.warning(f"Received invalid DNS request: {e}. Traceback: {traceback.format_exc()}.")
    return dns_request


async def get_dns_reply(callback: DnsCallback, dns_request: DNSRecord) -> DNSRecord:
    """
    This function calls the callback, and returns SERVFAIL if the callback raises an exception.
    """
    try:
        dns_reply = await callback(dns_request)
    except Exception as e:
        log.error(f"Exception during DNS record processing: {e}. Traceback: {traceback.format_exc()}.")
        # we return an empty response with an error code
        dns_reply = create_dns_reply(dns_request)  # This is an empty response, with only the header set.
        dns_reply.header.rcode = RCODE.SERVFAIL
    return dns_reply


@dataclass
class DNSServer:
    config: Dict[str, Any]
    root_path: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)
    crawl_store: Optional[CrawlStore] = field(init=False, default=None)
    reliable_task: Optional[asyncio.Task[None]] = field(init=False, default=None)
    shutting_down: bool = field(init=False, default=False)
    udp_transport_ipv4: Optional[asyncio.DatagramTransport] = field(init=False, default=None)
    udp_protocol_ipv4: Optional[UDPDNSServerProtocol] = field(init=False, default=None)
    udp_transport_ipv6: Optional[asyncio.DatagramTransport] = field(init=False, default=None)
    udp_protocol_ipv6: Optional[UDPDNSServerProtocol] = field(init=False, default=None)
    # TODO: After 3.10 is dropped change to asyncio.Server
    tcp_server: Optional[asyncio.base_events.Server] = field(init=False, default=None)
    # these are all set in __post_init__
    tcp_dns_port: int = field(init=False)
    udp_dns_port: int = field(init=False)
    db_path: Path = field(init=False)
    domain: DomainName = field(init=False)
    ns1: DomainName = field(init=False)
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
        # From Config:
        # The dns ports should only really be different if testing.
        self.tcp_dns_port: int = self.config.get("dns_port", 53)
        self.udp_dns_port: int = self.config.get("dns_port", 53)
        # DB Path:
        crawler_db_path: str = self.config.get("crawler_db_path", "crawler.db")
        self.db_path: Path = path_from_root(self.root_path, crawler_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # DNS info:
        self.domain: DomainName = DomainName(self.config["domain_name"])
        if not self.domain.endswith("."):
            self.domain = DomainName(self.domain + ".")  # Make sure the domain ends with a period, as per RFC 1035.
        self.ns1: DomainName = DomainName(self.config["nameserver"])
        self.ns_records: List[NS] = [NS(self.ns1)]
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
        log.warning("Starting DNS server.")
        # Get a reference to the event loop as we plan to use low-level APIs.
        loop = asyncio.get_running_loop()

        # Set up the crawl store and the peer update task.
        self.crawl_store = await CrawlStore.create(await aiosqlite.connect(self.db_path, timeout=120))
        self.reliable_task = asyncio.create_task(self.periodically_get_reliable_peers())

        # One protocol instance will be created for each udp transport, so that we can accept ipv4 and ipv6
        self.udp_transport_ipv6, self.udp_protocol_ipv6 = await loop.create_datagram_endpoint(
            lambda: UDPDNSServerProtocol(self.dns_response), local_addr=("::0", self.udp_dns_port)
        )
        self.udp_protocol_ipv6.start()  # start ipv6 udp transmit task

        # in case the port is 0, we get the real port
        self.udp_dns_port = self.udp_transport_ipv6.get_extra_info("sockname")[1]  # get the port we bound to

        if sys.platform.startswith("win32") or sys.platform.startswith("cygwin"):
            # Windows does not support dual stack sockets, so we need to create a new socket for ipv4.
            self.udp_transport_ipv4, self.udp_protocol_ipv4 = await loop.create_datagram_endpoint(
                lambda: UDPDNSServerProtocol(self.dns_response), local_addr=("0.0.0.0", self.udp_dns_port)
            )
            self.udp_protocol_ipv4.start()  # start ipv4 udp transmit task

        # One tcp server will handle both ipv4 and ipv6 on both linux and windows.
        self.tcp_server = await loop.create_server(
            lambda: TCPDNSServerProtocol(self.dns_response), ["::0", "0.0.0.0"], self.tcp_dns_port
        )

        log.warning("DNS server started.")
        try:
            yield
        finally:  # catches any errors and properly shuts down the server
            await self.stop()
            log.warning("DNS server stopped.")

    async def setup_process_global_state(self, signal_handlers: SignalHandlers) -> None:
        signal_handlers.setup_async_signal_handler(handler=self._accept_signal)

    async def _accept_signal(
        self,
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None:  # pragma: no cover
        log.info("Received signal %s (%s), shutting down.", signal_.name, signal_.value)
        await self.stop()

    async def stop(self) -> None:
        log.warning("Stopping DNS server...")
        if self.shutting_down:
            return
        self.shutting_down = True
        if self.reliable_task is not None:
            self.reliable_task.cancel()  # cancel the peer update task
        if self.crawl_store is not None:
            await self.crawl_store.crawl_db.close()
        if self.udp_protocol_ipv6 is not None:
            await self.udp_protocol_ipv6.stop()  # stop responding to and accepting udp requests (ipv6) & ipv4 if linux.
        if self.udp_protocol_ipv4 is not None:
            await self.udp_protocol_ipv4.stop()  # stop responding to and accepting udp requests (ipv4) if windows.
        if self.tcp_server is not None:
            self.tcp_server.close()  # stop accepting new tcp requests (ipv4 and ipv6)
            await self.tcp_server.wait_closed()  # wait for existing TCP requests to finish (ipv4 and ipv6)
        self.shutdown_event.set()

    async def periodically_get_reliable_peers(self) -> None:
        sleep_interval = 0
        while not self.shutdown_event.is_set() and self.crawl_store is not None:
            try:
                new_reliable_peers = await self.crawl_store.get_good_peers()
            except Exception as e:
                log.error(f"Error loading reliable peers from database: {e}. Traceback: {traceback.format_exc()}.")
                continue
            if len(new_reliable_peers) == 0:
                log.warning("No reliable peers found in database, waiting for db to be populated.")
                await asyncio.sleep(2)  # sleep for 2 seconds, because the db has not been populated yet.
                continue
            async with self.lock:
                self.reliable_peers_v4 = []
                self.reliable_peers_v6 = []
                self.pointer_v4 = 0
                self.pointer_v6 = 0
                for peer in new_reliable_peers:
                    try:
                        validated_peer = ip_address(peer)
                        if validated_peer.version == 4:
                            self.reliable_peers_v4.append(validated_peer)
                        elif validated_peer.version == 6:
                            self.reliable_peers_v6.append(validated_peer)
                    except ValueError:
                        log.error(f"Invalid peer: {peer}")
                        continue
                log.warning(
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
        reply = create_dns_reply(request)
        dns_question: DNSQuestion = request.q  # this is the question / request
        question_type: int = dns_question.qtype  # the type of the record being requested
        qname = dns_question.qname  # the name being queried / requested
        # ADD EDNS0 to response if supported
        if len(request.ar) > 0 and request.ar[0].rtype == QTYPE.OPT:  # OPT Means EDNS
            udp_len = min(4096, request.ar[0].edns_len)
            edns_reply = EDNS0(udp_len=udp_len)
            reply.add_ar(edns_reply)
        # DNS labels are mixed case with DNS resolvers that implement the use of bit 0x20 to improve
        # transaction identity. See https://datatracker.ietf.org/doc/html/draft-vixie-dnsext-dns0x20-00
        qname_str = str(qname).lower()
        if qname_str != self.domain and not qname_str.endswith(f".{self.domain}"):
            # we don't answer for other domains (we have the not recursive bit set)
            log.warning(f"Invalid request for {qname_str}, returning REFUSED.")
            reply.header.rcode = RCODE.REFUSED
            return reply

        ttl: int = self.ttl
        # we add these to the list as it will allow us to respond to ns and soa requests
        ips: List[RD] = [self.soa_record] + self.ns_records
        ipv4_count = 0
        ipv6_count = 0
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
        ips.extend([A(str(peer)) for peer in peers.ipv4])
        ips.extend([AAAA(str(peer)) for peer in peers.ipv6])

        records: Dict[DomainName, List[RD]] = {  # this is where we can add other records we want to serve
            self.domain: ips,
        }

        valid_domain = False
        for domain_name, domain_responses in records.items():
            if domain_name == qname_str:  # if the dns name is the same as the requested name
                valid_domain = True
                for response in domain_responses:
                    rqt: int = getattr(QTYPE, response.__class__.__name__)
                    if question_type == rqt or question_type == QTYPE.ANY:
                        reply.add_answer(RR(rname=qname, rtype=rqt, rclass=1, ttl=ttl, rdata=response))
        if not valid_domain and len(reply.rr) == 0:  # if we didn't find any records to return
            reply.header.rcode = RCODE.NXDOMAIN
        # always put nameservers and the SOA records
        for nameserver in self.ns_records:
            reply.add_auth(RR(rname=self.domain, rtype=QTYPE.NS, rclass=1, ttl=ttl, rdata=nameserver))
        reply.add_auth(RR(rname=self.domain, rtype=QTYPE.SOA, rclass=1, ttl=ttl, rdata=self.soa_record))
        return reply


async def run_dns_server(dns_server: DNSServer) -> None:  # pragma: no cover
    async with SignalHandlers.manage() as signal_handlers:
        await dns_server.setup_process_global_state(signal_handlers=signal_handlers)
        async with dns_server.run():
            await dns_server.shutdown_event.wait()  # this is released on SIGINT or SIGTERM or any unhandled exception


def create_dns_server_service(config: Dict[str, Any], root_path: Path) -> DNSServer:
    service_config = config[SERVICE_NAME]

    return DNSServer(service_config, root_path)


def main() -> None:  # pragma: no cover
    freeze_support()
    root_path = DEFAULT_ROOT_PATH
    # TODO: refactor to avoid the double load
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    initialize_service_logging(service_name=SERVICE_NAME, config=config)

    dns_server = create_dns_server_service(config, root_path)
    asyncio.run(run_dns_server(dns_server))


if __name__ == "__main__":
    main()
