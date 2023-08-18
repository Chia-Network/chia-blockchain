from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Tuple

import pytest
import pytest_asyncio

from chia.consensus.constants import ConsensusConstants
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools, test_constants
from chia.simulator.setup_services import setup_full_node, setup_timelord, setup_vdf_clients
from chia.simulator.socket import find_available_listen_port
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.util.ints import uint16
from tests.conftest import Mode

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


def get_height(node: FullNodeAPI) -> int:
    peak = node.full_node.blockchain.get_peak()
    if peak is None:
        return 0
    return peak.height


@pytest_asyncio.fixture(scope="function")
async def simple_sim(
    consensus_mode: Mode, get_b_tools: BlockTools
) -> AsyncGenerator[Tuple[Service[FullNode, FullNodeAPI], Service[Timelord, TimelordAPI], object], None]:
    if consensus_mode != Mode.PLAIN:
        pytest.skip("Skipping this run. This test only supports one running at a time.")
    async for _ in setup_small_system(
        test_constants_modified,
        b_tools=get_b_tools,
    ):
        yield _


async def setup_small_system(
    consensus_constants: ConsensusConstants,
    b_tools: BlockTools,
    db_version: int = 2,
) -> AsyncGenerator[Tuple[Service[FullNode, FullNodeAPI], Service[Timelord, TimelordAPI], object], None]:
    b_tools.config["full_node"]["enable_upnp"] = False
    full_node_iter = setup_full_node(
        consensus_constants,
        "blockchain_test.db",
        "localhost",
        b_tools,
        introducer_port=None,
        simulator=False,
        send_uncompact_interval=10,
        sanitize_weight_proof_only=False,
        connect_to_daemon=False,
        db_version=db_version,
    )
    node = await full_node_iter.__anext__()

    vdf1_port = uint16(find_available_listen_port("vdf1"))
    timelord_iter = setup_timelord(
        full_node_port=node._api.full_node.server.get_port(),
        sanitizer=False,
        consensus_constants=consensus_constants,
        b_tools=b_tools,
        vdf_port=vdf1_port,
    )
    vdf_clients_iter = setup_vdf_clients(b_tools, "localhost", vdf1_port)
    node_iters = [
        vdf_clients_iter,
        timelord_iter,
        full_node_iter,
    ]

    ret = (
        node,
        await timelord_iter.__anext__(),
        await vdf_clients_iter.__anext__(),
    )

    yield ret

    awaitables = [i.__anext__() for i in node_iters]
    for sublist_awaitable in asyncio.as_completed(awaitables):
        try:
            await sublist_awaitable
        except StopAsyncIteration:
            pass


async def testy_test(
    node: Service[FullNode, FullNodeAPI],
    timelord: Service[Timelord, TimelordAPI],
) -> None:
    await asyncio.sleep(10)
    # print(f"timelord port: {timelord._server.get_port()}")
    # print(f"node1 port: {node._node.server.get_port()}")

    print(f"timelord: {timelord._server.get_connections()}")
    print(f"node1: {node._node.server.get_connections()}")

    # print(f"Node1 height: {get_height(node._api)}")

    # await asyncio.sleep(15)
    # print(f"Node1 height: {get_height(node._api)}")
    # await asyncio.sleep(15)
    # print(f"Node1 height: {get_height(node._api)}")
    # await asyncio.sleep(15)
    # print(f"Node1 height: {get_height(node._api)}")

    # timelord.stop()
    # await timelord.wait_closed()

    # node.stop()
    # await node.wait_closed()

    await asyncio.sleep(120)
    return


@pytest.mark.asyncio
async def test_one(
    simple_sim: Tuple[
        Service[FullNode, FullNodeAPI],
        Service[Timelord, TimelordAPI],
        Tuple[asyncio.Task[Any], asyncio.Task[Any], asyncio.Task[Any]],
    ]
) -> None:
    node: Service[FullNode, FullNodeAPI]
    timelord: Service[Timelord, TimelordAPI]
    vdf_clients: Tuple[asyncio.Task[Any], asyncio.Task[Any], asyncio.Task[Any]]
    (
        node,
        timelord,
        vdf_clients,
    ) = simple_sim

    await testy_test(node, timelord)

    return


@pytest.mark.asyncio
async def test_two(
    simple_sim: Tuple[
        Service[FullNode, FullNodeAPI],
        Service[Timelord, TimelordAPI],
        Tuple[asyncio.Task[Any], asyncio.Task[Any], asyncio.Task[Any]],
    ]
) -> None:
    node: Service[FullNode, FullNodeAPI]
    timelord: Service[Timelord, TimelordAPI]
    vdf_clients: Tuple[asyncio.Task[Any], asyncio.Task[Any], asyncio.Task[Any]]
    (
        node,
        timelord,
        vdf_clients,
    ) = simple_sim

    await testy_test(node, timelord)

    return
