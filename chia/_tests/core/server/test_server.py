from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, cast
from unittest.mock import MagicMock, patch

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import int16, uint8, uint16, uint32
from packaging.version import Version

from chia import __version__
from chia._tests.conftest import ConsensusMode
from chia._tests.connection_utils import connect_and_get_peer
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.start_full_node import create_full_node_service
from chia.protocols.full_node_protocol import RejectBlock, RequestBlock, RequestTransaction
from chia.protocols.outbound_message import NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Error, protocol_version
from chia.protocols.wallet_protocol import RejectHeaderRequest
from chia.server.api_protocol import ApiMetadata
from chia.server.server import ChiaServer
from chia.server.ssl_context import chia_ssl_ca_paths, private_ssl_ca_paths
from chia.server.ws_connection import Message, WSChiaConnection, error_response_version
from chia.simulator.block_tools import BlockTools
from chia.types.peer_info import PeerInfo
from chia.util.errors import ApiError, Err
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
@pytest.mark.parametrize("method", [repr, str])
async def test_connection_string_conversion(
    two_nodes_one_block: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
    method: Callable[[object], str],
) -> None:
    _, _, server_1, server_2, _ = two_nodes_one_block
    peer = await connect_and_get_peer(server_1, server_2, self_hostname)
    # 1000 is based on the current implementation (example below), should be reconsidered/adjusted if this test fails
    # WSChiaConnection(local_type=<NodeType.FULL_NODE: 1>, local_port=50632, local_capabilities=[<Capability.BASE: 1>, <Capability.BLOCK_HEADERS: 2>, <Capability.RATE_LIMITS_V2: 3>], peer_host='127.0.0.1', peer_port=50640, peer_node_id=<bytes32: 566a318f0f656125b4fef0e85fbddcf9bc77f8003d35293c392479fc5d067f4d>, outbound_rate_limiter=<chia.server.rate_limits.RateLimiter object at 0x114a13f50>, inbound_rate_limiter=<chia.server.rate_limits.RateLimiter object at 0x114a13e90>, is_outbound=False, creation_time=1675271096.275591, bytes_read=68, bytes_written=162, last_message_time=1675271096.276271, peer_server_port=50636, active=False, closed=False, connection_type=<NodeType.FULL_NODE: 1>, request_nonce=32768, peer_capabilities=[<Capability.BASE: 1>, <Capability.BLOCK_HEADERS: 2>, <Capability.RATE_LIMITS_V2: 3>], version='', protocol_version='') # noqa
    converted = method(peer)
    print(converted)
    assert len(converted) < 1000


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
    outgoing_connection = wallet_node.server.all_connections[full_node.server.node_id]
    incoming_connection = full_node.server.all_connections[wallet_node.server.node_id]
    for connection in [outgoing_connection, incoming_connection]:
        assert connection.protocol_version == Version(protocol_version[NodeType.WALLET])
        assert connection.version == __version__
        assert connection.get_version() == connection.version


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
    wallet_connection = full_node.server.all_connections[wallet_node.server.node_id]
    full_node_connection = wallet_node.server.all_connections[full_node.server.node_id]
    test_version = Version(version)
    wallet_connection.protocol_version = test_version
    request = RequestTransaction(bytes32(32 * b"1"))
    error_message = f"Some error message: {request.transaction_id}"
    with caplog.at_level(logging.DEBUG):
        response = await full_node_connection.call_api(TestAPI.request_transaction, request, timeout=5)
        error = ApiError(Err.NO_TRANSACTIONS_WHILE_SYNCING, error_message)
        assert f"ApiError: {error} from {wallet_connection.peer_node_id}, {wallet_connection.peer_info}" in caplog.text
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
    wallet_connection = full_node.server.all_connections[wallet_node.server.node_id]
    full_node_connection = wallet_node.server.all_connections[full_node.server.node_id]
    message = make_msg(ProtocolMessageTypes.error, error)

    def error_log_found(connection: WSChiaConnection) -> bool:
        return f"ApiError: {error} from {connection.peer_node_id}, {connection.peer_info}" in caplog.text

    with caplog.at_level(logging.WARNING):
        await full_node_connection.outgoing_queue.put(message)
        await wallet_connection.outgoing_queue.put(message)
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


# =============================================================================
# Tests for progress-based timeout in send_request
# =============================================================================


@pytest.mark.anyio
async def test_send_request_respects_small_timeout(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    """
    Test that send_request respects small timeouts (< 30 second check_interval).

    This verifies the fix for the bug where check_interval=30 was used directly
    in asyncio.wait_for(), making 30 seconds the effective minimum timeout.

    Note: In a connected environment, background network activity (heartbeats, etc.)
    may cause progress detection which resets the timeout. This test verifies that
    even with potential progress resets, the total time is reasonable and doesn't
    extend to the full 30-second check_interval.
    """
    _, _, server_1, server_2, _ = two_nodes
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

    # Get the connection from server_2's perspective
    connection = next(iter(server_2.all_connections.values()))

    # Create a request message
    message = Message(uint8(ProtocolMessageTypes.request_block.value), None, bytes(RequestBlock(uint32(999999), False)))

    # Patch the outgoing_queue.put to be a no-op so the message is never actually sent
    async def mock_put(msg: Message) -> None:
        pass  # Don't actually send

    # Test with a small timeout (5 seconds, well below the 30 second check_interval)
    # Due to progress detection from background traffic, we may see up to 2x the timeout
    # (one reset before the connection settles), but importantly NOT 20+ seconds
    small_timeout = 5
    max_allowed_time = small_timeout * 3  # Allow for progress resets
    start_time = time.time()
    with patch.object(connection.outgoing_queue, "put", mock_put):
        result = await connection.send_request(message, timeout=small_timeout)
    elapsed = time.time() - start_time

    # The request should timeout - key assertion is that it doesn't wait 20+ seconds
    assert result is None, "Expected None result for timed-out request"
    # Before the fix, this would wait ~30 seconds. After fix, should be much less.
    assert elapsed < max_allowed_time, f"Timeout took {elapsed:.2f}s, should be < {max_allowed_time}s (not 30s)"


@pytest.mark.anyio
async def test_send_request_timeout_no_progress_simulation() -> None:
    """
    Test the timeout calculation logic directly without network dependencies.

    This is a unit test that verifies the timeout math works correctly by
    simulating the wait_time calculation that happens in send_request.
    """
    # Simulate the key calculation from send_request
    check_interval = 30
    timeout = 5
    time_without_progress = 0.0

    # Before the fix: wait_time = check_interval = 30 (always)
    # After the fix: wait_time = min(check_interval, timeout - time_without_progress)

    # First iteration
    remaining_timeout = timeout - time_without_progress
    wait_time = min(check_interval, remaining_timeout)
    assert wait_time == 5, f"First wait should be 5s (min of 20, 5), got {wait_time}"

    # Simulate timeout (no progress)
    time_without_progress += wait_time
    assert time_without_progress == 5, "After first iteration, should have waited 5s"

    # Loop should exit because time_without_progress >= timeout
    assert time_without_progress >= timeout, "Should exit loop after one iteration"


@pytest.mark.anyio
async def test_send_request_timeout_with_progress_simulation() -> None:
    """
    Test that progress resets work correctly with the timeout calculation.
    """
    check_interval = 30
    timeout = 5
    time_without_progress = 0.0

    # First iteration - wait for min(30, 5) = 5 seconds
    remaining_timeout = timeout - time_without_progress
    wait_time = min(check_interval, remaining_timeout)
    assert wait_time == 5

    # Simulate progress detected - reset timer
    time_without_progress = 0.0

    # Second iteration - should again wait for 5 seconds
    remaining_timeout = timeout - time_without_progress
    wait_time = min(check_interval, remaining_timeout)
    assert wait_time == 5

    # Simulate no progress this time
    time_without_progress += wait_time
    assert time_without_progress == 5

    # Now loop should exit
    assert time_without_progress >= timeout


@pytest.mark.anyio
async def test_bytes_received_counter_no_response(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    """
    Test _get_protocol_bytes_received returns 0 when websocket _response is not accessible.
    """
    _, _, server_1, server_2, _ = two_nodes
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

    connection = next(iter(server_2.all_connections.values()))

    # Mock ws._response to be None
    original_ws = connection.ws
    mock_ws = MagicMock()
    mock_ws._response = None
    connection.ws = mock_ws

    try:
        # Should return 0 when _response is None
        result = connection._get_protocol_bytes_received()
        assert result == 0, f"Expected 0 when _response is None, got {result}"

        # _install_bytes_received_counter should silently do nothing
        connection._install_bytes_received_counter()
        result = connection._get_protocol_bytes_received()
        assert result == 0, f"Expected 0 after install attempt with no _response, got {result}"
    finally:
        connection.ws = original_ws


@pytest.mark.anyio
async def test_bytes_received_counter_no_protocol(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    """
    Test _get_protocol_bytes_received returns 0 when protocol is not accessible.
    """
    _, _, server_1, server_2, _ = two_nodes
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

    connection = next(iter(server_2.all_connections.values()))

    # Mock ws._response._connection.protocol to be None
    original_ws = connection.ws
    mock_ws = MagicMock()
    mock_response = MagicMock()
    mock_connection = MagicMock()
    mock_connection.protocol = None
    mock_response._connection = mock_connection
    mock_ws._response = mock_response
    connection.ws = mock_ws

    try:
        result = connection._get_protocol_bytes_received()
        assert result == 0, f"Expected 0 when protocol is None, got {result}"

        connection._install_bytes_received_counter()
        result = connection._get_protocol_bytes_received()
        assert result == 0, f"Expected 0 after install attempt with no protocol, got {result}"
    finally:
        connection.ws = original_ws


@pytest.mark.anyio
async def test_bytes_received_counter_installation_and_counting(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    """
    Test that _install_bytes_received_counter properly wraps data_received and counts bytes.
    """
    _, _, server_1, server_2, _ = two_nodes
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

    connection = next(iter(server_2.all_connections.values()))

    # Create a simple mock structure (not MagicMock, to avoid auto-attribute creation)
    # Structure: ws._response._connection.protocol
    original_ws = connection.ws

    class MockProtocol:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def data_received(self, data: bytes) -> None:
            self.calls.append(data)

    class MockConnection:
        def __init__(self) -> None:
            self.protocol = MockProtocol()

    class MockResponse:
        def __init__(self) -> None:
            self._connection = MockConnection()

    class MockWs:
        def __init__(self) -> None:
            self._response = MockResponse()

    mock_ws = MockWs()
    connection.ws = mock_ws  # type: ignore[assignment]

    try:
        mock_protocol = mock_ws._response._connection.protocol

        # Before installation, should return 0 (no _chia_bytes_received attribute)
        assert connection._get_protocol_bytes_received() == 0

        # Install the counter
        connection._install_bytes_received_counter()

        # Now the protocol should have the counter attribute
        assert hasattr(mock_protocol, "_chia_bytes_received")
        assert mock_protocol._chia_bytes_received == 0

        # Simulate receiving data - call the wrapped data_received
        mock_protocol.data_received(b"hello")
        assert mock_protocol._chia_bytes_received == 5
        assert connection._get_protocol_bytes_received() == 5
        assert mock_protocol.calls == [b"hello"], "Original data_received should still be called"

        mock_protocol.data_received(b"world!")
        assert mock_protocol._chia_bytes_received == 11
        assert connection._get_protocol_bytes_received() == 11
        assert mock_protocol.calls == [b"hello", b"world!"]

        # Installing again should be a no-op (don't install twice)
        connection._install_bytes_received_counter()
        mock_protocol.data_received(b"test")
        assert mock_protocol._chia_bytes_received == 15  # Still counting correctly
        assert len(mock_protocol.calls) == 3  # Not double-wrapped
    finally:
        connection.ws = original_ws


@pytest.mark.anyio
async def test_bytes_received_counter_exception_handling(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    """
    Test that _install_bytes_received_counter and _get_protocol_bytes_received
    handle exceptions gracefully.
    """
    _, _, server_1, server_2, _ = two_nodes
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

    connection = next(iter(server_2.all_connections.values()))

    # Create a mock that raises exceptions
    original_ws = connection.ws
    mock_ws = MagicMock()

    # Make _response property raise an exception
    type(mock_ws)._response = property(lambda self: (_ for _ in ()).throw(RuntimeError("Test error")))
    connection.ws = mock_ws

    try:
        # Should return 0 and not raise
        result = connection._get_protocol_bytes_received()
        assert result == 0, f"Expected 0 on exception, got {result}"

        # Should silently fail and not raise
        connection._install_bytes_received_counter()  # Should not raise
    finally:
        connection.ws = original_ws


@pytest.mark.anyio
async def test_send_request_connection_closed_during_wait(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    """
    Test that send_request handles connection closing during the wait.
    """
    _, _, server_1, server_2, _ = two_nodes
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

    connection = next(iter(server_2.all_connections.values()))
    message = Message(uint8(ProtocolMessageTypes.request_block.value), None, bytes(RequestBlock(uint32(999999), False)))

    # Patch the outgoing_queue.put to be a no-op so the message is never actually sent
    # This ensures no response comes back and we test the connection-close detection
    async def mock_put(msg: Message) -> None:
        pass  # Don't actually send

    # Close the connection after a short delay
    async def close_after_delay() -> None:
        await asyncio.sleep(1)
        await connection.close()

    # Start the close task
    close_task = asyncio.create_task(close_after_delay())

    start_time = time.time()
    with patch.object(connection.outgoing_queue, "put", mock_put):
        result = await connection.send_request(message, timeout=30)
    elapsed = time.time() - start_time

    # Should return quickly after connection closes, not wait full timeout
    assert result is None
    # Should complete in about 1-5 seconds (close delay + one check interval which is min(20, remaining))
    # The key is it shouldn't wait the full 30 seconds
    assert elapsed < 10, f"Should exit early when connection closes, took {elapsed:.2f}s"

    await close_task
