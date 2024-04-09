from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Tuple, cast

import pytest
from packaging.version import Version

from chia import __version__
from chia._tests.connection_utils import connect_and_get_peer
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import RejectBlock, RequestBlock, RequestTransaction
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Error, protocol_version
from chia.protocols.wallet_protocol import RejectHeaderRequest
from chia.server.outbound_message import NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.start_full_node import create_full_node_service
from chia.server.start_wallet import create_wallet_service
from chia.server.ws_connection import WSChiaConnection, error_response_version
from chia.simulator.block_tools import BlockTools
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.api_decorators import api_request
from chia.util.errors import ApiError, Err
from chia.util.ints import int16, uint32


@dataclass
class TestAPI:
    log: logging.Logger = logging.getLogger(__name__)

    def ready(self) -> bool:
        return True

    # API call from FullNodeAPI
    @api_request()
    async def request_transaction(self, request: RequestTransaction) -> None:
        raise ApiError(Err.NO_TRANSACTIONS_WHILE_SYNCING, f"Some error message: {request.transaction_id}", b"ab")


@pytest.mark.anyio
async def test_duplicate_client_connection(
    two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    _, _, server_1, server_2, _ = two_nodes
    assert await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
    assert not await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)


@pytest.mark.anyio
@pytest.mark.parametrize("method", [repr, str])
async def test_connection_string_conversion(
    two_nodes_one_block: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
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
    two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
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
    two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools]
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
