from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import signal
import traceback
from pathlib import Path
from typing import Any, Dict, List

import aiosqlite
from dnslib import AAAA, CNAME, MX, NS, QTYPE, RR, SOA, A, DNSHeader, DNSRecord

from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root

SERVICE_NAME = "seeder"
log = logging.getLogger(__name__)

# DNS snippet taken from: https://gist.github.com/pklaus/b5a7876d4d2cf7271873


class DomainName(str):
    def __getattr__(self, item):
        return DomainName(item + "." + self)


D = None
ns = None
IP = "127.0.0.1"
TTL = None
soa_record = None
ns_records: List[Any] = []


class EchoServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, callback):
        self.data_queue = asyncio.Queue()
        self.callback = callback
        asyncio.ensure_future(self.respond())

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.ensure_future(self.handler(data, addr))

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


class DNSServer:
    reliable_peers_v4: List[str]
    reliable_peers_v6: List[str]
    lock: asyncio.Lock
    pointer: int
    crawl_db: aiosqlite.Connection

    def __init__(self, config: Dict, root_path: Path):
        self.reliable_peers_v4 = []
        self.reliable_peers_v6 = []
        self.lock = asyncio.Lock()
        self.pointer_v4 = 0
        self.pointer_v6 = 0

        crawler_db_path: str = config.get("crawler_db_path", "crawler.db")
        self.db_path = path_from_root(root_path, crawler_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def start(self):
        # self.crawl_db = await aiosqlite.connect(self.db_path)
        # Get a reference to the event loop as we plan to use
        # low-level APIs.
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all
        # client requests.
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: EchoServerProtocol(self.dns_response), local_addr=("::0", 53)
        )
        self.reliable_task = asyncio.create_task(self.periodically_get_reliable_peers())

    async def periodically_get_reliable_peers(self):
        sleep_interval = 0
        while True:
            try:
                # TODO: double check this. It shouldn't take this long to connect.
                crawl_db = await aiosqlite.connect(self.db_path, timeout=600)
                cursor = await crawl_db.execute(
                    "SELECT * from good_peers",
                )
                new_reliable_peers = []
                rows = await cursor.fetchall()
                await cursor.close()
                await crawl_db.close()
                for row in rows:
                    new_reliable_peers.append(row[0])
                if len(new_reliable_peers) > 0:
                    random.shuffle(new_reliable_peers)
                async with self.lock:
                    self.reliable_peers_v4 = []
                    self.reliable_peers_v6 = []
                    for peer in new_reliable_peers:
                        ipv4 = True
                        try:
                            _ = ipaddress.IPv4Address(peer)
                        except ValueError:
                            ipv4 = False
                        if ipv4:
                            self.reliable_peers_v4.append(peer)
                        else:
                            try:
                                _ = ipaddress.IPv6Address(peer)
                            except ValueError:
                                continue
                            self.reliable_peers_v6.append(peer)
                    self.pointer_v4 = 0
                    self.pointer_v6 = 0
                log.error(
                    f"Number of reliable peers discovered in dns server:"
                    f" IPv4 count - {len(self.reliable_peers_v4)}"
                    f" IPv6 count - {len(self.reliable_peers_v6)}"
                )
            except Exception as e:
                log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

            sleep_interval = min(15, sleep_interval + 1)
            await asyncio.sleep(sleep_interval * 60)

    async def get_peers_to_respond(self, ipv4_count, ipv6_count):
        peers = []
        async with self.lock:
            # Append IPv4.
            size = len(self.reliable_peers_v4)
            if ipv4_count > 0 and size <= ipv4_count:
                peers = self.reliable_peers_v4
            elif ipv4_count > 0:
                peers = [self.reliable_peers_v4[i % size] for i in range(self.pointer_v4, self.pointer_v4 + ipv4_count)]
                self.pointer_v4 = (self.pointer_v4 + ipv4_count) % size
            # Append IPv6.
            size = len(self.reliable_peers_v6)
            if ipv6_count > 0 and size <= ipv6_count:
                peers = peers + self.reliable_peers_v6
            elif ipv6_count > 0:
                peers = peers + [
                    self.reliable_peers_v6[i % size] for i in range(self.pointer_v6, self.pointer_v6 + ipv6_count)
                ]
                self.pointer_v6 = (self.pointer_v6 + ipv6_count) % size
            return peers

    async def dns_response(self, data):
        try:
            request = DNSRecord.parse(data)
            IPs = [MX(D.mail), soa_record] + ns_records
            ipv4_count = 0
            ipv6_count = 0
            if request.q.qtype == 1:
                ipv4_count = 32
            elif request.q.qtype == 28:
                ipv6_count = 32
            elif request.q.qtype == 255:
                ipv4_count = 16
                ipv6_count = 16
            else:
                ipv4_count = 32
            peers = await self.get_peers_to_respond(ipv4_count, ipv6_count)
            if len(peers) == 0:
                return None
            for peer in peers:
                ipv4 = True
                try:
                    _ = ipaddress.IPv4Address(peer)
                except ValueError:
                    ipv4 = False
                if ipv4:
                    IPs.append(A(peer))
                else:
                    try:
                        _ = ipaddress.IPv6Address(peer)
                    except ValueError:
                        continue
                    IPs.append(AAAA(peer))
            reply = DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=len(IPs), ra=1), q=request.q)

            records = {
                D: IPs,
                D.ns1: [A(IP)],  # MX and NS records must never point to a CNAME alias (RFC 2181 section 10.3)
                D.ns2: [A(IP)],
                D.mail: [A(IP)],
                D.andrei: [CNAME(D)],
            }

            qname = request.q.qname
            # DNS labels are mixed case with DNS resolvers that implement the use of bit 0x20 to improve
            # transaction identity. See https://datatracker.ietf.org/doc/html/draft-vixie-dnsext-dns0x20-00
            qn = str(qname).lower()
            qtype = request.q.qtype
            qt = QTYPE[qtype]
            if qn == D or qn.endswith("." + D):
                for name, rrs in records.items():
                    if name == qn:
                        for rdata in rrs:
                            rqt = rdata.__class__.__name__
                            if qt in ["*", rqt] or (qt == "ANY" and (rqt == "A" or rqt == "AAAA")):
                                reply.add_answer(
                                    RR(rname=qname, rtype=getattr(QTYPE, rqt), rclass=1, ttl=TTL, rdata=rdata)
                                )

                for rdata in ns_records:
                    reply.add_ar(RR(rname=D, rtype=QTYPE.NS, rclass=1, ttl=TTL, rdata=rdata))

                reply.add_auth(RR(rname=D, rtype=QTYPE.SOA, rclass=1, ttl=TTL, rdata=soa_record))

            return reply.pack()
        except Exception as e:
            log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")


async def serve_dns(config: Dict, root_path: Path):
    dns_server = DNSServer(config, root_path)
    await dns_server.start()

    # TODO: Make this cleaner?
    while True:
        await asyncio.sleep(3600)


async def kill_processes():
    # TODO: implement.
    pass


def signal_received():
    asyncio.create_task(kill_processes())


async def async_main(config, root_path):
    loop = asyncio.get_running_loop()

    try:
        loop.add_signal_handler(signal.SIGINT, signal_received)
        loop.add_signal_handler(signal.SIGTERM, signal_received)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    await serve_dns(config, root_path)


def main():
    root_path = DEFAULT_ROOT_PATH
    config = load_config(root_path, "config.yaml", SERVICE_NAME)
    initialize_logging(SERVICE_NAME, config["logging"], root_path)
    global D
    global ns
    global TTL
    global soa_record
    global ns_records
    D = DomainName(config["domain_name"])
    ns = DomainName(config["nameserver"])
    TTL = config["ttl"]
    soa_record = SOA(
        mname=ns,  # primary name server
        rname=config["soa"]["rname"],  # email of the domain administrator
        times=(
            config["soa"]["serial_number"],
            config["soa"]["refresh"],
            config["soa"]["retry"],
            config["soa"]["expire"],
            config["soa"]["minimum"],
        ),
    )
    ns_records = [NS(ns)]

    asyncio.run(async_main(config=config, root_path=root_path))


if __name__ == "__main__":
    main()
