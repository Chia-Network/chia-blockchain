from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, cast

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import int16, uint8, uint16, uint32
from packaging.version import Version

from chia import __version__
from chia._tests.conftest import ConsensusMode
from chia._tests.connection_utils import add_dummy_connection_wsc, connect_and_get_peer
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.start_full_node import create_full_node_service
from chia.protocols.full_node_protocol import RejectBlock, RequestBlock, RequestTransaction
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Error, protocol_version
from chia.protocols.wallet_protocol import RejectHeaderRequest
from chia.server.api_protocol import ApiMetadata
from chia.server.server import ChiaServer
from chia.server.ssl_context import chia_ssl_ca_paths, private_ssl_ca_paths
from chia.server.ws_connection import WSChiaConnection, error_response_version, sanitize_version_string
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.peer_info import PeerInfo
from chia.util.errors import ApiError, Err
from chia.util.task_referencer import create_referenced_task
from chia.wallet.start_wallet import create_wallet_service


@dataclass
class TestAPI:
    log: logging.Logger = logging.getLogger(__name__)
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        return True

    # API call from FullNodeAPI
    @metadata.request()
    async def request_transaction(self, request: RequestTransaction) -> None:
        raise ApiError(Err.NO_TRANSACTIONS_WHILE_SYNCING, f"Some error message: {request.transaction_id}", b"ab")


@pytest.mark.anyio
async def test_duplicate_client_connection(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    _, _, server_1, server_2, _ = two_nodes
    assert await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
    assert not await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)


@pytest.mark.anyio
async def test_start_client_handshake_timeout(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, _, server_1, server_2, _ = two_nodes

    async def timeout_handshake(
        self: WSChiaConnection, network_id: str, server_port: uint16, local_type: NodeType
    ) -> None:
        raise asyncio.TimeoutError

    monkeypatch.setattr(WSChiaConnection, "perform_handshake", timeout_handshake)
    target_peer = PeerInfo(self_hostname, server_2.get_port())
    with caplog.at_level(logging.DEBUG):
        assert not await server_1.start_client(target_peer, None)
    assert f"Handshake timeout connecting to {target_peer}" in caplog.text


@pytest.mark.anyio
async def test_start_client_handshake_timeout_configurable(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, _, server_1, server_2, _ = two_nodes

    recorded_timeouts: list[float | None] = []
    original_wait_for = asyncio.wait_for

    async def capturing_wait_for(fut: object, *, timeout: float | None = None) -> object:
        recorded_timeouts.append(timeout)
        return await original_wait_for(fut, timeout=timeout)  # type: ignore[arg-type]

    monkeypatch.setattr(asyncio, "wait_for", capturing_wait_for)
    monkeypatch.setattr("chia.server.server.is_localhost", lambda _host: False)
    server_1.config["outbound_handshake_timeout"] = 42
    target_peer = PeerInfo(self_hostname, server_2.get_port())
    with caplog.at_level(logging.DEBUG):
        await server_1.start_client(target_peer, None)
    assert 42.0 in recorded_timeouts


@pytest.mark.anyio
@pytest.mark.parametrize("method", [repr, str])
async def test_connection_string_conversion(
    two_nodes_one_block: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
    method: Callable[[object], str],
) -> None:
    _, _, server_1, server_2, _ = two_nodes_one_block
    peer = await connect_and_get_peer(server_1, server_2, self_hostname)
    # 1100 is based on the current implementation (example below), should be reconsidered/adjusted if this test fails
    # WSChiaConnection(local_type=<NodeType.FULL_NODE: 1>, local_port=50632, local_capabilities=[<Capability.BASE: 1>, <Capability.BLOCK_HEADERS: 2>, <Capability.RATE_LIMITS_V2: 3>, <Capability.MEMPOOL_UPDATES: 5>, <Capability.HARD_FORK_2: 6>], peer_info=PeerInfo(_ip=IPv4Address('127.0.0.1'), _port=50640), peer_node_id=<bytes32: 566a318f0f656125b4fef0e85fbddcf9bc77f8003d35293c392479fc5d067f4d>, outbound_rate_limiter=<chia.server.rate_limits.RateLimiter object at 0x114a13f50>, inbound_rate_limiter=<chia.server.rate_limits.RateLimiter object at 0x114a13e90>, is_outbound=False, creation_time=1675271096.275591, bytes_read=68, bytes_written=162, last_message_time=1675271096.276271, peer_server_port=50636, closed=False, connection_type=<NodeType.FULL_NODE: 1>, request_nonce=32768, peer_capabilities=[<Capability.BASE: 1>, <Capability.BLOCK_HEADERS: 2>, <Capability.RATE_LIMITS_V2: 3>, <Capability.MEMPOOL_UPDATES: 5>, <Capability.HARD_FORK_2: 6>], version='', protocol_version=<Version('0.0.36')>) # noqa
    converted = method(peer)
    print(converted)
    assert len(converted) < 1200


@pytest.mark.anyio
async def test_connection_versions(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices
) -> None:
    [full_node_service], [wallet_service], _ = one_wallet_and_one_simulator_services
    wallet_node = wallet_service._node
    full_node = full_node_service._node
    await wallet_node.server.start_client(
        PeerInfo(self_hostname, cast(FullNodeAPI, full_node_service._api).server.get_port()), None
    )
    await time_out_assert(5, lambda: full_node.server.node_id in wallet_node.server.all_connections)
    outgoing_connection = wallet_node.server.all_connections[full_node.server.node_id]
    await time_out_assert(5, lambda: wallet_node.server.node_id in full_node.server.all_connections)
    incoming_connection = full_node.server.all_connections[wallet_node.server.node_id]
    for connection in [outgoing_connection, incoming_connection]:
        assert connection.protocol_version == Version(protocol_version[NodeType.WALLET])
        assert connection.version == __version__
        assert connection.get_version() == connection.version


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2.5.0", "2.5.0"),
        ("", ""),
        ("2.5.0\nERROR fake log line", "2.5.0ERROR fake log line"),
        ("2.5.0\r\nINJECTED", "2.5.0INJECTED"),
        ("2.5.0\x00hidden", "2.5.0hidden"),
        ("\x1b[31mred\x1b[0m", "[31mred[0m"),
        ("valid-version_1.2.3+build.42", "valid-version_1.2.3+build.42"),
        ("a" * 128, "a" * 128),
        ("\u200b\u200czero-width", "zero-width"),
    ],
)
def test_sanitize_version_string(raw: str, expected: str) -> None:
    assert sanitize_version_string(raw) == expected


@pytest.mark.anyio
async def test_api_not_ready(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    caplog: pytest.LogCaptureFixture,
) -> None:
    [full_node_service], [wallet_service], _ = one_wallet_and_one_simulator_services
    wallet_node = wallet_service._node
    full_node = full_node_service._node
    await wallet_node.server.start_client(
        PeerInfo(self_hostname, cast(FullNodeAPI, full_node_service._api).server.get_port()), None
    )
    wallet_node.log_out()
    assert not wallet_service._api.ready()
    await time_out_assert(5, lambda: wallet_node.server.node_id in full_node.server.all_connections)
    connection = full_node.server.all_connections[wallet_node.server.node_id]

    def request_ignored() -> bool:
        return "API not ready, ignore request: {'data': '0x00000000', 'id': None, 'type': 53}" in caplog.text

    with caplog.at_level(logging.WARNING):
        assert await connection.send_message(
            make_msg(ProtocolMessageTypes.reject_header_request, RejectHeaderRequest(uint32(0)))
        )
        await time_out_assert(10, request_ignored)


@pytest.mark.parametrize("version", ["0.0.34", "0.0.35", "0.0.36"])
@pytest.mark.anyio
async def test_error_response(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    self_hostname: str,
    caplog: pytest.LogCaptureFixture,
    version: str,
) -> None:
    [full_node_service], [wallet_service], _ = one_wallet_and_one_simulator_services
    wallet_node = wallet_service._node
    full_node = full_node_service._node

    full_node.server.api = TestAPI()

    await wallet_node.server.start_client(
        PeerInfo(self_hostname, cast(FullNodeAPI, full_node_service._api).server.get_port()), None
    )
    test_version = Version(version)
    request = RequestTransaction(bytes32(32 * b"1"))
    error_message = f"Some error message: {request.transaction_id}"
    dummy_wsc, dummy_peer_id = await add_dummy_connection_wsc(
        full_node.server, self_hostname, 1337, wait_for_peer_added=False
    )
    await time_out_assert(5, lambda: dummy_peer_id in full_node.server.all_connections)
    dummy_full_node_connection = full_node.server.all_connections[dummy_peer_id]
    dummy_full_node_connection.protocol_version = test_version
    with caplog.at_level(logging.DEBUG):
        response = await dummy_wsc.call_api(TestAPI.request_transaction, request, timeout=5)
        error = ApiError(Err.NO_TRANSACTIONS_WHILE_SYNCING, error_message)
        assert (
            f"ApiError: {error} from {dummy_full_node_connection.peer_node_id}, {dummy_full_node_connection.peer_info}"
            in caplog.text
        )
        if test_version >= error_response_version:
            assert response == Error(int16(Err.NO_TRANSACTIONS_WHILE_SYNCING.value), error_message, b"ab")
            assert "Request timeout:" not in caplog.text
        else:
            assert response is None
            assert "Request timeout:" in caplog.text


@pytest.mark.parametrize(
    "error", [Error(int16(Err.UNKNOWN.value), "1", bytes([1, 2, 3])), Error(int16(Err.UNKNOWN.value), "2", None)]
)
@pytest.mark.anyio
async def test_error_receive(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    self_hostname: str,
    caplog: pytest.LogCaptureFixture,
    error: Error,
) -> None:
    [full_node_service], [wallet_service], _ = one_wallet_and_one_simulator_services
    wallet_node = wallet_service._node
    full_node = full_node_service._node
    await wallet_node.server.start_client(
        PeerInfo(self_hostname, cast(FullNodeAPI, full_node_service._api).server.get_port()), None
    )
    await time_out_assert(5, lambda: wallet_node.server.node_id in full_node.server.all_connections)
    wallet_connection = full_node.server.all_connections[wallet_node.server.node_id]
    await time_out_assert(5, lambda: full_node.server.node_id in wallet_node.server.all_connections)
    full_node_connection = wallet_node.server.all_connections[full_node.server.node_id]
    message = make_msg(ProtocolMessageTypes.error, error)

    def error_log_found(connection: WSChiaConnection) -> bool:
        return f"ApiError: {error} from {connection.peer_node_id}, {connection.peer_info}" in caplog.text

    with caplog.at_level(logging.WARNING):
        await full_node_connection.outgoing_queue.put((0, 0, message))
        await wallet_connection.outgoing_queue.put((0, 1, message))
        await time_out_assert(10, error_log_found, True, full_node_connection)
        await time_out_assert(10, error_log_found, True, wallet_connection)


@pytest.mark.anyio
async def test_call_api_of_specific(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    _, _, server_1, server_2, _ = two_nodes
    assert await server_1.start_client(PeerInfo(self_hostname, server_2.get_port()), None)

    message = await server_1.call_api_of_specific(
        FullNodeAPI.request_block, RequestBlock(uint32(42), False), server_2.node_id
    )

    assert message is not None
    assert isinstance(message, RejectBlock)


@pytest.mark.anyio
async def test_call_api_of_specific_for_missing_peer(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
) -> None:
    _, _, server_1, server_2, _ = two_nodes

    message = await server_1.call_api_of_specific(
        FullNodeAPI.request_block, RequestBlock(uint32(42), False), server_2.node_id
    )

    assert message is None


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_get_peer_info(bt: BlockTools) -> None:
    wallet_service = create_wallet_service(
        bt.root_path, bt.config, bt.constants, keychain=None, connect_to_daemon=False
    )

    # Wallet server should not have a port or peer info
    with pytest.raises(ValueError, match="Port not set"):
        local_port = wallet_service._server.get_port()
    local_peer_info = await wallet_service._server.get_peer_info()
    assert local_peer_info is None

    # Full node server should have a local port
    # testing get_peer_info() directly is flakey because it depends on IP lookup
    # from either chia or aws
    node_service = await create_full_node_service(bt.root_path, bt.config, bt.constants, connect_to_daemon=False)
    local_port = node_service._server.get_port()
    assert local_port is not None


class FakeConnection:
    connection_type: NodeType = NodeType.FULL_NODE
    peer_node_id: bytes32 = bytes32(b"\x00" * 32)

    def __init__(self, peer_info: PeerInfo) -> None:
        self.peer_info = peer_info

    def cancel_tasks(self) -> None:
        pass


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="save time")
@pytest.mark.anyio
async def test_connection_closed_banning(bt: BlockTools, caplog: pytest.LogCaptureFixture) -> None:
    test_config = bt.config["full_node"]
    private_ca_crt, private_ca_key = private_ssl_ca_paths(bt.root_path, bt.config)
    chia_ca_crt, chia_ca_key = chia_ssl_ca_paths(bt.root_path, bt.config)

    # need to add in exempt networks to config
    test_config["exempt_peer_networks"] = ["10.1.1.0/16"]
    test_config["trusted_cidrs"] = ["34.34.34.34/32"]

    my_test_server = ChiaServer.create(
        port=None,
        node=None,
        api=FullNodeAPI(None),  # type: ignore[arg-type]
        local_type=NodeType.FULL_NODE,
        ping_interval=0,
        network_id="Fake",
        root_path=bt.root_path,
        capabilities=[],
        outbound_rate_limit_percent=100,
        inbound_rate_limit_percent=100,
        config=test_config,
        private_ca_crt_key=(private_ca_crt, private_ca_key),
        chia_ca_crt_key=(chia_ca_crt, chia_ca_key),
        stub_metadata_for_type={},
        name="Hello",
    )

    with caplog.at_level(logging.WARNING):
        # testing exempt_peer_networks
        exempt_peer = FakeConnection(peer_info=PeerInfo("10.1.1.1", 8444))
        await my_test_server.connection_closed(cast(WSChiaConnection, exempt_peer), ban_time=60)
        assert f"Trying to ban exempt peer {exempt_peer.peer_info.host} for 60, but will not ban" in caplog.text

        # testing localhost exemption
        localhost_peer = FakeConnection(peer_info=PeerInfo("127.0.0.1", 8444))
        await my_test_server.connection_closed(cast(WSChiaConnection, localhost_peer), ban_time=60)
        assert "Trying to ban localhost for 60, but will not ban" in caplog.text

        # testing trusted peers exemption
        trusted_peer = FakeConnection(peer_info=PeerInfo("34.34.34.34", 8444))
        await my_test_server.connection_closed(cast(WSChiaConnection, trusted_peer), ban_time=60)
        assert f"Trying to ban trusted peer {trusted_peer.peer_info.host} for 60, but will not ban" in caplog.text


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_route_incoming_message(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools], self_hostname: str
) -> None:
    """
    Covers the scenarios where incoming messages are responses to active
    requests, responses to timed out requests (late) and the rest.
    """
    _, server, _ = one_node_one_block
    wsc, _ = await add_dummy_connection_wsc(server, self_hostname, 1337)
    test_response_type = uint8(ProtocolMessageTypes.respond_block.value)
    # In time message gets handled via the response route
    response_event = asyncio.Event()
    pending_request_id = uint16(5)
    wsc.pending_requests[pending_request_id] = response_event
    in_time_msg = Message(type=test_response_type, id=pending_request_id, data=b"")
    await wsc._route_incoming_message(in_time_msg)
    assert wsc.request_results[pending_request_id] == in_time_msg
    assert response_event.is_set()
    # Timed out message gets dropped
    timed_out_request_id = uint16(6)
    wsc.timed_out_requests.add(timed_out_request_id)
    timed_out_msg = Message(type=test_response_type, id=timed_out_request_id, data=b"")
    incoming_queue_size = wsc.incoming_queue.qsize()
    await wsc._route_incoming_message(timed_out_msg)
    assert timed_out_request_id not in wsc.timed_out_requests
    # The incoming queue size doesn't increase as the message got dropped
    assert wsc.incoming_queue.qsize() == incoming_queue_size
    # Other messages are forwarded to the incoming queue
    other_msg = Message(test_response_type, uint16(7), b"")
    await wsc._route_incoming_message(other_msg)
    assert wsc.incoming_queue.qsize() == incoming_queue_size + 1


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("is_outbound, range_start, range_end", [(True, 0, 2**15 - 1), (False, 2**15, 2**16 - 1)])
async def test_select_request_nonce(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    is_outbound: bool,
    range_start: int,
    range_end: int,
) -> None:
    """
    Covers the scenarios of skipping active nonces, selecting nonces that are
    available in range, wraps occurring and no available nonces. We control
    inbound/outbound via `is_outbound`.
    """
    _, server, _ = one_node_one_block
    wsc, _ = await add_dummy_connection_wsc(server, self_hostname, 1337)
    wsc.is_outbound = is_outbound
    # Skip used nonces
    wsc.pending_requests[uint16(range_start)] = asyncio.Event()
    wsc.timed_out_requests.add(uint16(range_start + 1))
    wsc.request_nonce = uint16(range_start)
    assert wsc._select_request_nonce() == uint16(range_start + 2)
    assert wsc.request_nonce == uint16(range_start + 3)
    # Make sure that next selection skips properly if `request_nonce` points to
    # a reserved nonce after successful allocation.
    wsc.pending_requests.clear()
    wsc.timed_out_requests.clear()
    wsc.pending_requests[uint16(range_start)] = asyncio.Event()
    wsc.timed_out_requests.add(uint16(range_start + 1))
    wsc.pending_requests[uint16(range_start + 3)] = asyncio.Event()
    wsc.request_nonce = uint16(range_start)
    assert wsc._select_request_nonce() == uint16(range_start + 2)
    # This points to a reserved nonce
    assert wsc.request_nonce == uint16(range_start + 3)
    wsc.timed_out_requests.add(uint16(range_start + 4))
    # Next selection should skip the reserved nonce and the timed out nonce
    assert wsc._select_request_nonce() == uint16(range_start + 5)
    assert wsc.request_nonce == uint16(range_start + 6)
    # Nonce in range and unused
    wsc.request_nonce = uint16(range_start + 2)
    wsc.pending_requests.clear()
    wsc.timed_out_requests.clear()
    assert wsc._select_request_nonce() == uint16(range_start + 2)
    assert wsc.request_nonce == uint16(range_start + 3)
    # Wrap stays within inbound/outbound range
    wsc.pending_requests.clear()
    wsc.timed_out_requests.clear()
    wsc.pending_requests[uint16(range_end)] = asyncio.Event()
    wsc.request_nonce = uint16(range_end)
    assert wsc._select_request_nonce() == uint16(range_start)
    assert wsc.request_nonce == uint16(range_start + 1)
    # No nonces available
    wsc.pending_requests.clear()
    wsc.timed_out_requests.clear()
    for nonce in range(range_start, range_end + 1):
        wsc.pending_requests[uint16(nonce)] = asyncio.Event()
    wsc.request_nonce = uint16(range_start)
    assert wsc._select_request_nonce() is None
    # Make sure we don't advance in this case
    assert wsc.request_nonce == uint16(range_start)
    # With no nonces currently available, send a request and make sure the
    # connection gets closed.
    msg = make_msg(ProtocolMessageTypes.request_block, RequestBlock(uint32(42), False))
    response = await wsc.send_request(message_no_id=msg, timeout=1)
    assert response is None
    assert wsc.closed


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_inbound_handler_none_msg(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where the inbound handler receives `None` from
    `_read_one_message`.
    """
    _, server, _ = one_node_one_block
    wsc, _ = await add_dummy_connection_wsc(server, self_hostname, 1337)
    read_calls = 0

    async def test_read_one_message() -> Message | None:
        nonlocal read_calls
        read_calls += 1
        return None

    monkeypatch.setattr(wsc, "_read_one_message", test_read_one_message)
    assert wsc.inbound_task is not None
    wsc.inbound_task.cancel()
    wsc.inbound_task = create_referenced_task(wsc.inbound_handler())
    await asyncio.wait_for(wsc.inbound_task, timeout=1)
    assert read_calls == 1
    assert wsc.incoming_queue.qsize() == 0
    await wsc.close()


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_send_message_timed_out_nonced_request(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Covers the scenario where a nonced request gets timed out while it's in the
    outgoing queue to make sure it gets dropped.
    """
    _, server, _ = one_node_one_block
    wsc, _ = await add_dummy_connection_wsc(server, self_hostname, 1337)
    event = asyncio.Event()
    original_send_message = wsc._send_message
    request_id: uint16 | None = None

    async def test_send_message(message: Message, priority: int = 0) -> None:
        nonlocal request_id
        request_id = message.id
        await event.wait()
        await original_send_message(message, priority=priority)

    monkeypatch.setattr(wsc, "_send_message", test_send_message)
    msg_type = ProtocolMessageTypes.request_block
    msg = make_msg(msg_type, b"")
    response = await wsc.send_request(message_no_id=msg, timeout=0)
    assert response is None
    assert request_id in wsc.timed_out_requests
    caplog.clear()
    caplog.set_level(logging.INFO)
    event.set()
    await time_out_assert(
        5, lambda: f"Dropping timed out request ID {request_id} with msg type {msg_type.name}" in caplog.text
    )
    assert request_id not in wsc.timed_out_requests
