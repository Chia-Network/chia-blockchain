from __future__ import annotations

import logging
import time
from typing import cast

import pytest

from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import NewPeak
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RequestChildren
from chia.seeder.peer_record import PeerRecord, PeerReliability
from chia.server.outbound_message import make_msg
from chia.types.aliases import CrawlerService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32, uint64, uint128


@pytest.mark.anyio
async def test_unknown_messages(
    self_hostname: str,
    one_node: SimulatorsAndWalletsServices,
    crawler_service: CrawlerService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    [full_node_service], _, _ = one_node
    crawler = crawler_service._node
    full_node = full_node_service._node
    assert await crawler.server.start_client(
        PeerInfo(self_hostname, cast(FullNodeAPI, full_node_service._api).server.get_port()), None
    )
    connection = full_node.server.all_connections[crawler.server.node_id]

    def receiving_failed() -> bool:
        return "Non existing function: request_children" in caplog.text

    with caplog.at_level(logging.ERROR):
        msg = make_msg(ProtocolMessageTypes.request_children, RequestChildren(bytes32(b"\0" * 32)))
        assert await connection.send_message(msg)
        await time_out_assert(10, receiving_failed)


@pytest.mark.anyio
async def test_valid_message(
    self_hostname: str,
    one_node: SimulatorsAndWalletsServices,
    crawler_service: CrawlerService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    [full_node_service], _, _ = one_node
    crawler = crawler_service._node
    full_node = full_node_service._node
    assert await crawler.server.start_client(
        PeerInfo(self_hostname, cast(FullNodeAPI, full_node_service._api).server.get_port()), None
    )
    connection = full_node.server.all_connections[crawler.server.node_id]

    def peer_added() -> bool:
        return crawler.server.all_connections[full_node.server.node_id].get_peer_logging() in crawler.with_peak

    msg = make_msg(
        ProtocolMessageTypes.new_peak,
        NewPeak(bytes32(b"\0" * 32), uint32(2), uint128(1), uint32(1), bytes32(b"\1" * 32)),
    )
    assert await connection.send_message(msg)
    await time_out_assert(10, peer_added)


@pytest.mark.anyio
async def test_crawler_to_db(crawler_service: CrawlerService, one_node: SimulatorsAndWalletsServices) -> None:
    """
    This is a lot more of an integration test, but it tests the whole process. We add a node to the crawler, then we
    save it to the db and validate.
    """
    [full_node_service], _, _ = one_node
    full_node = full_node_service._node
    crawler = crawler_service._node
    crawl_store = crawler.crawl_store
    assert crawl_store is not None
    peer_address = "127.0.0.1"

    # create peer records
    peer_record = PeerRecord(
        peer_address,
        peer_address,
        uint32(full_node.server.get_port()),
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
    peer_reliability = PeerReliability(peer_address, tries=1, successes=1)

    # add peer to the db & mark it as connected
    await crawl_store.add_peer(peer_record, peer_reliability)
    assert peer_record == crawl_store.host_to_records[peer_address]

    # validate the db data
    await time_out_assert(20, crawl_store.get_good_peers, [peer_address])
