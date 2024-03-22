from __future__ import annotations

import time
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from socket import AF_INET, AF_INET6, SOCK_STREAM
from typing import Dict, List, Tuple, cast

import dns
import pytest

from chia._tests.util.time_out_assert import time_out_assert
from chia.seeder.dns_server import DNSServer
from chia.seeder.peer_record import PeerRecord, PeerReliability
from chia.util.ints import uint32, uint64

timeout = 0.5


def generate_test_combs() -> List[Tuple[bool, str, dns.rdatatype.RdataType]]:
    """
    Generates all the combinations of tests we want to run.
    """
    output = []
    use_tcp = [True, False]
    target_address = ["::1", "127.0.0.1"]
    request_types = [dns.rdatatype.A, dns.rdatatype.AAAA, dns.rdatatype.ANY, dns.rdatatype.NS, dns.rdatatype.SOA]
    # (use_tcp, target-addr, request_type), so udp + tcp, ipv6 +4 for every request type we support.
    for addr in target_address:
        for tcp in use_tcp:
            for req in request_types:
                output.append((tcp, addr, req))
    return output


def get_dns_port(dns_server: DNSServer, use_tcp: bool, target_addr: str) -> int:
    if use_tcp:
        assert dns_server.tcp_server is not None
        tcp_sockets = dns_server.tcp_server.sockets
        wanted_addr = "::" if target_addr == "::1" else "0.0.0.0"
        if tcp_sockets[0].getsockname()[0] == wanted_addr:
            return int(tcp_sockets[0].getsockname()[1])
        return int(tcp_sockets[1].getsockname()[1])
    return dns_server.udp_dns_port


all_test_combinations = generate_test_combs()


@dataclass(frozen=True)
class FakeDnsPacket:
    real_packet: dns.message.Message

    def to_wire(self) -> bytes:
        return self.real_packet.to_wire()[23:]

    def __getattr__(self, item: object) -> None:
        # This is definitely cheating, but it works
        return None


@pytest.fixture(scope="module")
def database_peers() -> Dict[str, PeerReliability]:
    """
    We override the values in the class with these dbs, to save time.
    """
    host_to_reliability = {}
    ipv4, ipv6 = get_addresses(2)  # get 1000 addresses
    # add peers to the in memory part of the db.
    for peer in [str(peer) for pair in zip(ipv4, ipv6) for peer in pair]:
        new_peer = PeerRecord(
            peer,
            peer,
            uint32(58444),
            False,
            uint64(0),
            uint32(0),
            uint64(0),
            uint64(int(time.time())),
            uint64(0),
            "undefined",
            uint64(0),
            tls_version="unknown",
        )
        new_peer_reliability = PeerReliability(peer, tries=3, successes=3)  # make sure the peer starts as reliable.
        host_to_reliability[new_peer.peer_id] = new_peer_reliability
    return host_to_reliability


async def make_dns_query(
    use_tcp: bool, target_address: str, port: int, dns_message: dns.message.Message, d_timeout: float = timeout
) -> dns.message.Message:
    """
    Makes a DNS query for the given domain name using the given protocol type.
    """
    if use_tcp:
        return await dns.asyncquery.tcp(q=dns_message, where=target_address, timeout=d_timeout, port=port)
    return await dns.asyncquery.udp(q=dns_message, where=target_address, timeout=d_timeout, port=port)


def get_addresses(num_subnets: int = 10) -> Tuple[List[IPv4Address], List[IPv6Address]]:
    ipv4 = []
    ipv6 = []
    # generate 2500 ipv4 and 2500 ipv6 peers, it's just a string so who cares
    for s in range(num_subnets):
        for i in range(1, 251):  # im being lazy as we can only have 255 per subnet
            ipv4.append(IPv4Address(f"192.168.{s}.{i}"))
            ipv6.append(IPv6Address(f"2001:db8::{s}:{i}"))
    return ipv4, ipv6


def assert_standard_results(
    std_query_answer: List[dns.rrset.RRset], request_type: dns.rdatatype.RdataType, num_ns: int
) -> None:
    if request_type == dns.rdatatype.A:
        assert len(std_query_answer) == 1  # only 1 kind of answer
        a_answer = std_query_answer[0]
        assert a_answer.rdtype == dns.rdatatype.A
        assert len(a_answer) == 32  # 32 ipv4 addresses
    elif request_type == dns.rdatatype.AAAA:
        assert len(std_query_answer) == 1  # only 1 kind of answer
        aaaa_answer = std_query_answer[0]
        assert aaaa_answer.rdtype == dns.rdatatype.AAAA
        assert len(aaaa_answer) == 32  # 32 ipv6 addresses
    elif request_type == dns.rdatatype.ANY:
        assert len(std_query_answer) == 4  # 4 kinds of answers
        for answer in std_query_answer:
            if answer.rdtype == dns.rdatatype.A:
                assert len(answer) == 16
            elif answer.rdtype == dns.rdatatype.AAAA:
                assert len(answer) == 16
            elif answer.rdtype == dns.rdatatype.NS:
                assert len(answer) == num_ns
            else:
                assert len(answer) == 1
    elif request_type == dns.rdatatype.NS:
        assert len(std_query_answer) == 1  # only 1 kind of answer
        ns_answer = std_query_answer[0]
        assert ns_answer.rdtype == dns.rdatatype.NS
        assert len(ns_answer) == num_ns  # ns records
    else:
        assert len(std_query_answer) == 1  # soa
        soa_answer = std_query_answer[0]
        assert soa_answer.rdtype == dns.rdatatype.SOA
        assert len(soa_answer) == 1


@pytest.mark.skip(reason="Flaky test with fixes in progress")
@pytest.mark.anyio
@pytest.mark.parametrize("use_tcp, target_address, request_type", all_test_combinations)
async def test_error_conditions(
    seeder_service: DNSServer, use_tcp: bool, target_address: str, request_type: dns.rdatatype.RdataType
) -> None:
    """
    We check having no peers, an invalid packet, an early EOF, and a packet then an EOF halfway through (tcp only).
    We also check for a dns record that does not exist, and a dns record outside the domain.
    """
    port = get_dns_port(seeder_service, use_tcp, target_address)
    domain = seeder_service.domain  # default is: seeder.example.com
    num_ns = len(seeder_service.ns_records)

    # No peers
    no_peers = dns.message.make_query(domain, request_type)
    no_peers_response = await make_dns_query(use_tcp, target_address, port, no_peers)
    assert no_peers_response.rcode() == dns.rcode.NOERROR

    if request_type == dns.rdatatype.A or request_type == dns.rdatatype.AAAA:
        assert len(no_peers_response.answer) == 0  # no response, as expected
    elif request_type == dns.rdatatype.ANY:  # ns + soa
        assert len(no_peers_response.answer) == 2
        for answer in no_peers_response.answer:
            if answer.rdtype == dns.rdatatype.NS:
                assert len(answer.items) == num_ns
            else:
                assert len(answer.items) == 1
    elif request_type == dns.rdatatype.NS:
        assert len(no_peers_response.answer) == 1  # ns
        assert no_peers_response.answer[0].rdtype == dns.rdatatype.NS
        assert len(no_peers_response.answer[0].items) == num_ns
    else:
        assert len(no_peers_response.answer) == 1  # soa
        assert no_peers_response.answer[0].rdtype == dns.rdatatype.SOA
        assert len(no_peers_response.answer[0].items) == 1
    # Authority Records
    assert len(no_peers_response.authority) == num_ns + 1  # ns + soa
    for record_list in no_peers_response.authority:
        if record_list.rdtype == dns.rdatatype.NS:
            assert len(record_list.items) == num_ns
        else:
            assert len(record_list.items) == 1  # soa

    # Invalid packet (this is kinda a pain)
    invalid_packet = cast(dns.message.Message, FakeDnsPacket(dns.message.make_query(domain, request_type)))
    with pytest.raises(EOFError if use_tcp else dns.exception.Timeout):  # UDP will time out, TCP will EOF
        await make_dns_query(use_tcp, target_address, port, invalid_packet)

    # early EOF packet
    proto, source_addr = (AF_INET6, "::") if target_address == "::1" else (AF_INET, "0.0.0.0")
    if use_tcp:
        backend = dns.asyncbackend.get_default_backend()
        tcp_socket = await backend.make_socket(  # type: ignore[no-untyped-call]
            proto, SOCK_STREAM, 0, (source_addr, 0), (target_address, port), timeout=timeout
        )
        async with tcp_socket as socket:
            await socket.close()
            with pytest.raises(EOFError):
                await dns.asyncquery.receive_tcp(tcp_socket, timeout)

    # Packet then length header then EOF
    if use_tcp:
        backend = dns.asyncbackend.get_default_backend()
        tcp_socket = await backend.make_socket(  # type: ignore[no-untyped-call]
            proto, SOCK_STREAM, 0, (source_addr, 0), (target_address, port), timeout=timeout
        )
        async with tcp_socket as socket:  # send packet then length then eof
            r = await dns.asyncquery.tcp(q=no_peers, where=target_address, timeout=timeout, sock=socket)
            assert r.answer == no_peers_response.answer
            # send 120, as the first 2 bytes / the length of the packet, so that the server expects more.
            await socket.sendall(int(120).to_bytes(2, byteorder="big"), int(time.time() + timeout))
            await socket.close()
            with pytest.raises(EOFError):
                await dns.asyncquery.receive_tcp(tcp_socket, timeout)

    # Record does not exist
    record_does_not_exist = dns.message.make_query("doesnotexist." + domain, request_type)
    record_does_not_exist_response = await make_dns_query(use_tcp, target_address, port, record_does_not_exist)
    assert record_does_not_exist_response.rcode() == dns.rcode.NXDOMAIN
    assert len(record_does_not_exist_response.answer) == 0
    assert len(record_does_not_exist_response.authority) == num_ns + 1  # ns + soa

    # Record outside domain
    record_outside_domain = dns.message.make_query("chia.net", request_type)
    record_outside_domain_response = await make_dns_query(use_tcp, target_address, port, record_outside_domain)
    assert record_outside_domain_response.rcode() == dns.rcode.REFUSED
    assert len(record_outside_domain_response.answer) == 0
    assert len(record_outside_domain_response.authority) == 0


@pytest.mark.skip(reason="Flaky test with fixes in progress")
@pytest.mark.anyio
@pytest.mark.parametrize("use_tcp, target_address, request_type", all_test_combinations)
async def test_dns_queries(
    seeder_service: DNSServer, use_tcp: bool, target_address: str, request_type: dns.rdatatype.RdataType
) -> None:
    """
    We add 5000 peers directly, then try every kind of query many times over both the TCP and UDP protocols.
    """
    port = get_dns_port(seeder_service, use_tcp, target_address)
    domain = seeder_service.domain  # default is: seeder.example.com
    num_ns = len(seeder_service.ns_records)

    # add 5000 peers (2500 ipv4, 2500 ipv6)
    seeder_service.reliable_peers_v4, seeder_service.reliable_peers_v6 = get_addresses()

    # now we query for each type of record a lot of times and make sure we get the right number of responses
    for i in range(150):
        query = dns.message.make_query(domain, request_type, use_edns=True)  # we need to generate a new request id.
        std_query_response = await make_dns_query(use_tcp, target_address, port, query)
        assert std_query_response.rcode() == dns.rcode.NOERROR
        assert_standard_results(std_query_response.answer, request_type, num_ns)

        # Assert Authority Records
        assert len(std_query_response.authority) == num_ns + 1  # ns + soa
        for record_list in std_query_response.authority:
            if record_list.rdtype == dns.rdatatype.NS:
                assert len(record_list.items) == num_ns
            else:
                assert len(record_list.items) == 1  # soa
    if not use_tcp:
        # Validate EDNS
        e_query = dns.message.make_query(domain, dns.rdatatype.ANY, use_edns=False)
        with pytest.raises(dns.query.BadResponse):  # response is truncated without EDNS
            await make_dns_query(use_tcp, target_address, port, e_query)


@pytest.mark.skip(reason="Flaky test with fixes in progress")
@pytest.mark.anyio
@pytest.mark.parametrize("use_tcp, target_address, request_type", all_test_combinations)
async def test_db_processing(
    seeder_service: DNSServer,
    database_peers: Dict[str, PeerReliability],
    use_tcp: bool,
    target_address: str,
    request_type: dns.rdatatype.RdataType,
) -> None:
    """
    We add 1000 peers through the db, then try every kind of query over both the TCP and UDP protocols.
    """
    port = get_dns_port(seeder_service, use_tcp, target_address)
    domain = seeder_service.domain  # default is: seeder.example.com
    num_ns = len(seeder_service.ns_records)
    crawl_store = seeder_service.crawl_store
    assert crawl_store is not None

    # override host_to_reliability with the pre-generated db peers
    crawl_store.host_to_reliability = database_peers

    # Write these new peers to db.
    await crawl_store.load_reliable_peers_to_db()

    # wait for the new db to be read.
    await time_out_assert(30, lambda: seeder_service.reliable_peers_v4 != [])

    # now we check that the db peers are being used.
    query = dns.message.make_query(domain, request_type, use_edns=True)  # we need to generate a new request id.
    std_query_response = await make_dns_query(use_tcp, target_address, port, query)
    assert std_query_response.rcode() == dns.rcode.NOERROR
    assert_standard_results(std_query_response.answer, request_type, num_ns)
