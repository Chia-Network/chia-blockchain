from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import dns.asyncresolver
import dns.rdataclass
import dns.rdatatype
import dns.resolver
import pytest
from chia_rs.sized_ints import uint16
from dns.rdtypes.IN.A import A

from chia.introducer.introducer import Introducer
from chia.introducer.introducer_api import IntroducerAPI
from chia.protocols.introducer_protocol import RequestPeersIntroducer, RespondPeersIntroducer
from chia.server.introducer_peers import IntroducerPeers
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo


class PartiallyFailingResolver:
    """Answers A queries, fails AAAA queries the way an IPv4-only seeder does."""

    async def resolve(self, qname: str, rdtype: str, lifetime: float) -> list[A]:
        if rdtype == "AAAA":
            raise dns.resolver.NoAnswer
        return [A(dns.rdataclass.IN, dns.rdatatype.A, "1.2.3.4")]  # type: ignore[no-untyped-call]


class FailingResolver:
    """Fails every query the way an unhealthy seeder does."""

    async def resolve(self, qname: str, rdtype: str, lifetime: float) -> list[A]:
        raise dns.resolver.NoNameservers


def make_introducer() -> Introducer:
    return Introducer(
        max_peers_to_send=20, recent_peer_threshold=6000, default_port=58444, dns_servers=["seeder.example.com"]
    )


@pytest.mark.anyio
async def test_get_peers_from_dns_keeps_partial_results() -> None:
    introducer = make_introducer()
    introducer.resolver = cast(dns.asyncresolver.Resolver, PartiallyFailingResolver())

    peers = await introducer.get_peers_from_dns(num_peers=10)

    assert [(peer.host, peer.port) for peer in peers] == [("1.2.3.4", 58444)]


@pytest.mark.anyio
async def test_request_peers_introducer_survives_dns_failure() -> None:
    introducer = make_introducer()
    introducer.resolver = cast(dns.asyncresolver.Resolver, FailingResolver())

    introducer_peers = IntroducerPeers()
    introducer_peers.add(PeerInfo("10.0.0.1", uint16(58444)))
    for vetted_peer in introducer_peers.get_peers():
        vetted_peer.vetted = 1
    introducer.set_server(cast(ChiaServer, SimpleNamespace(introducer_peers=introducer_peers)))
    requester = cast(
        WSChiaConnection, SimpleNamespace(peer_info=PeerInfo("10.0.0.2", uint16(58444)), peer_server_port=58444)
    )

    # Fewer vetted peers than max_peers_to_send forces the DNS fallback, which fails;
    # the vetted peers must still be returned.
    msg = await IntroducerAPI(introducer).request_peers_introducer(RequestPeersIntroducer(), requester)

    assert msg is not None
    response = RespondPeersIntroducer.from_bytes(msg.data)
    assert [(peer.host, peer.port) for peer in response.peer_list] == [("10.0.0.1", 58444)]
