from __future__ import annotations

from typing import List, AsyncGenerator, Tuple, AsyncIterator

import pytest
import pytest_asyncio

from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.shared_protocol import Capability
from chia.protocols.shared_protocol import capabilities as default_capabilities
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.server.ws_connection import compute_mutually_understood_capabilities
from chia.simulator.block_tools import BlockTools
from chia.simulator.setup_nodes import setup_full_system, setup_simulators_and_wallets_service, SimulatorsAndWallets
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from chia.wallet.wallet_node import WalletNode
from tests.conftest import node_with_params
from tests.core.consensus.test_pot_iterations import test_constants


constants = test_constants
caps_unknown_to_v2 = [Capability.BASE, Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2, 4]
protocol_v2 = [Capability.BASE, Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2]
protocol_v1 = [Capability.BASE]

wire_caps_unknown_to_v2 = [(uint16(c), "1") for c in caps_unknown_to_v2]
wire_protocol_v2 = [(uint16(c), "1") for c in protocol_v2]
wire_protocol_v1 = [(uint16(c), "1") for c in protocol_v1]

node_with_params_b = node_with_params
test_different_versions_results: List[int] = []


test_constants_modified = test_constants.replace(
    **{
        "DIFFICULTY_STARTING": 2**8,
        "DISCRIMINANT_SIZE_BITS": 1024,
        "SUB_EPOCH_BLOCKS": 140,
        "WEIGHT_PROOF_THRESHOLD": 2,
        "WEIGHT_PROOF_RECENT_BLOCKS": 350,
        "MAX_SUB_SLOT_BLOCKS": 50,
        "NUM_SPS_SUB_SLOT": 32,  # Must be a power of 2
        "EPOCH_BLOCKS": 280,
        "SUB_SLOT_ITERS_STARTING": 2**20,
        "NUMBER_ZERO_BITS_PLOT_FILTER": 5,
    }
)


@pytest_asyncio.fixture(scope="function")
async def simulation(bt: BlockTools) -> AsyncIterator[SimulatorsAndWallets]:
    async for _ in setup_full_system(test_constants_modified, bt, db_version=1):
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_node_one_wallet() -> AsyncGenerator[Tuple[Service[FullNode], Service[WalletNode]], None]:
    async for nodes in setup_simulators_and_wallets_service(1, 1, {}):
        full_nodes, wallets, _ = nodes
        yield full_nodes[0], wallets[0]


##################################


def test_compute_capabilities() -> None:
    m = compute_mutually_understood_capabilities(wire_protocol_v1, wire_protocol_v2)
    assert len(m) < len(caps_unknown_to_v2)
    assert m == [Capability(c) for c in protocol_v1]


@pytest.mark.asyncio
async def test_connect_peer_with_unknown_capability(
    two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    """
    Test that we can connect two nodes with dissimilar capabilities in their handshake.
    """
    full_node_api_1, full_node_api_2, server1, server2, bt = two_nodes
    node2_port: uint16 = server2.get_port()

    assert server1._local_capabilities_for_handshake == default_capabilities
    assert server2._local_capabilities_for_handshake == default_capabilities

    server2._local_capabilities_for_handshake = wire_caps_unknown_to_v2

    # Connect node 1 to node 2
    connected: bool = await server1.start_client(PeerInfo(self_hostname, node2_port))
    assert connected, f"node1 was unable to connect to node2 on port {node2_port}"
    assert len(server1.get_connections(NodeType.FULL_NODE, outbound=True)) >= 1


def test_that_known_capability_set_is_default_capability_set() -> None:
    """
    This test makes visible the set of capabilities used in this version.
    It can and should be changed if below is no longer the intention.
    """
    known_capabilities = set(map(uint16, Capability))
    handshake_capabilities = set([c[0] for c in default_capabilities])
    enabled_capabilities = set([c[0] for c in default_capabilities if c[1] == "1"])
    disabled_capabilities = handshake_capabilities - enabled_capabilities

    assert known_capabilities == handshake_capabilities
    assert enabled_capabilities == handshake_capabilities
    assert disabled_capabilities == set()


def test_default_capabilities(one_node_one_wallet: Tuple[Service[FullNode], Service[WalletNode]]) -> None:
    node, wallet_node = one_node_one_wallet
    default_node_capabilities = node._api.full_node.server._local_capabilities_for_handshake
    default_wallet_capabilities = wallet_node._server._local_capabilities_for_handshake

    assert default_wallet_capabilities == default_capabilities
    assert default_node_capabilities == default_capabilities
