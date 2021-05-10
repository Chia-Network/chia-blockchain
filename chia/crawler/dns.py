import asyncio
import logging
import signal
import random
import aiosqlite
import traceback
import ipaddress
from typing import List
from dnslib import A, SOA, NS, MX, CNAME, RR, DNSRecord, QTYPE, DNSHeader
from chia.util.chia_logging import initialize_logging
from chia.util.path import mkdir, path_from_root
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH

log = logging.getLogger(__name__)

# DNS snippet took from: https://gist.github.com/pklaus/b5a7876d4d2cf7271873


class DomainName(str):
    def __getattr__(self, item):
        return DomainName(item + "." + self)

D = DomainName("seeder.example.com.")
ns = DomainName("example.com.")
IP = "127.0.0.1"
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
    ),
)
ns_records = [NS(ns)]


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


class DNSServer:
    reliable_peers: List[str]
    lock: asyncio.Lock
    pointer: int
    crawl_db: aiosqlite.Connection

    def __init__(self):
        self.reliable_peers = []
        self.lock = asyncio.Lock()
        self.pointer = 0
        db_path_replaced: str = "crawler.db"
        root_path = DEFAULT_ROOT_PATH
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    async def start(self):
        # self.crawl_db = await aiosqlite.connect(self.db_path)
        # Get a reference to the event loop as we plan to use
        # low-level APIs.
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all
        # client requests.
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: EchoServerProtocol(self.dns_response), local_addr=("0.0.0.0", 53)
        )
        self.reliable_task = asyncio.create_task(self.periodically_get_reliable_peers())

    async def periodically_get_reliable_peers(self):
        while True:
            # Restore every 15 mins.
            await asyncio.sleep(15 * 60)
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
                    self.reliable_peers = new_reliable_peers
                    self.pointer = 0
                log.error(f"Number of reliable peers discovered in dns server: {len(self.reliable_peers)}")
            except Exception as e:
                log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")

    async def get_peers_to_respond(self):
        async with self.lock:
            size = len(self.reliable_peers)
            if size <= 32:
                return self.reliable_peers
            peers = [self.reliable_peers[i % size] for i in range(self.pointer, self.pointer + 32)]
            self.pointer = (self.pointer + 32) % size
            return peers

    async def dns_response(self, data):
        try:
            request = DNSRecord.parse(data)
            IPs = [MX(D.mail), soa_record] + ns_records
            peers = await self.get_peers_to_respond()
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
                # TODO: Re enable IPv6.
                # else:
                #    IPs.append(AAAA(peer.host))
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
            if qn == D or qn.endswith("." + D):
                for name, rrs in records.items():
                    if name == qn:
                        for rdata in rrs:
                            rqt = rdata.__class__.__name__
                            if qt in ["*", rqt]:
                                reply.add_answer(
                                    RR(rname=qname, rtype=getattr(QTYPE, rqt), rclass=1, ttl=TTL, rdata=rdata)
                                )

                for rdata in ns_records:
                    reply.add_ar(RR(rname=D, rtype=QTYPE.NS, rclass=1, ttl=TTL, rdata=rdata))

                reply.add_auth(RR(rname=D, rtype=QTYPE.SOA, rclass=1, ttl=TTL, rdata=soa_record))

            return reply.pack()
        except Exception as e:
            log.error(f"Exception: {e}. Traceback: {traceback.format_exc()}.")


async def serve_dns():
    dns_server = DNSServer()
    await dns_server.start()

    # TODO: Make this cleaner?
    while True:
        await asyncio.sleep(3600)


async def kill_processes():
    # TODO: implement.
    pass

def main():
    root_path = DEFAULT_ROOT_PATH
    service_name = "full_node"
    service_config = load_config(root_path, "config.yaml", service_name)
    initialize_logging(service_name, service_config["logging"], root_path)

    def signal_received():
        asyncio.create_task(kill_processes())

    loop = asyncio.get_event_loop()

    try:
        loop.add_signal_handler(signal.SIGINT, signal_received)
        loop.add_signal_handler(signal.SIGTERM, signal_received)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    try:
        loop.run_until_complete(serve_dns())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
