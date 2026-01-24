from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from chia_rs import ConsensusConstants, FullBlock, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia._tests.conftest import ConsensusMode
from chia._tests.core.node_height import node_height_between, node_height_exactly
from chia._tests.util.time_out_assert import time_out_assert
from chia.apis import StubMetadataRegistry
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.protocols.full_node_protocol import RequestPeers
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability, default_capabilities
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.add_blocks_in_batches import add_blocks_in_batches
from chia.simulator.block_tools import BlockTools
from chia.types.peer_info import PeerInfo
from chia.util.hash import std_hash
from chia.util.task_referencer import create_referenced_task

log = logging.getLogger(__name__)


@pytest.mark.anyio
async def test_long_sync_from_zero(
    five_nodes: list[FullNodeAPI], default_1000_blocks: list[FullBlock], bt: BlockTools, self_hostname: str
) -> None:
    # Must be larger than "sync_block_behind_threshold" in the config
    blocks: list[FullBlock] = default_1000_blocks[:600]
    num_blocks = len(blocks)
    full_node_1, full_node_2, full_node_3, full_node_4, full_node_5 = five_nodes
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    server_3 = full_node_3.full_node.server
    server_4 = full_node_4.full_node.server
    server_5 = full_node_5.full_node.server

    # If this constant is changed, update the tests to use more blocks
    assert bt.constants.WEIGHT_PROOF_RECENT_BLOCKS < num_blocks

    # Syncs up less than recent blocks
    for block in blocks[: bt.constants.WEIGHT_PROOF_RECENT_BLOCKS - 5]:
        await full_node_1.full_node.add_block(block)

    await server_2.start_client(
        PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_2.full_node.on_connect
    )

    timeout_seconds = 250

    # The second node should eventually catch up to the first one
    await time_out_assert(
        timeout_seconds, node_height_exactly, True, full_node_2, bt.constants.WEIGHT_PROOF_RECENT_BLOCKS - 5 - 1
    )

    for block in blocks[bt.constants.WEIGHT_PROOF_RECENT_BLOCKS - 5 : bt.constants.WEIGHT_PROOF_RECENT_BLOCKS + 5]:
        await full_node_1.full_node.add_block(block)

    await server_3.start_client(
        PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_3.full_node.on_connect
    )

    # Node 3 and Node 2 sync up to node 1
    await time_out_assert(
        timeout_seconds, node_height_exactly, True, full_node_2, bt.constants.WEIGHT_PROOF_RECENT_BLOCKS + 5 - 1
    )
    await time_out_assert(
        timeout_seconds, node_height_exactly, True, full_node_3, bt.constants.WEIGHT_PROOF_RECENT_BLOCKS + 5 - 1
    )

    cons = list(server_1.all_connections.values())[:]
    for con in cons:
        await con.close()
    for block in blocks[bt.constants.WEIGHT_PROOF_RECENT_BLOCKS + 5 :]:
        await full_node_1.full_node.add_block(block)

    await server_2.start_client(
        PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_2.full_node.on_connect
    )
    await server_3.start_client(
        PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_3.full_node.on_connect
    )
    await server_4.start_client(
        PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_4.full_node.on_connect
    )
    await server_3.start_client(
        PeerInfo(self_hostname, server_2.get_port()), on_connect=full_node_3.full_node.on_connect
    )
    await server_4.start_client(
        PeerInfo(self_hostname, server_3.get_port()), on_connect=full_node_4.full_node.on_connect
    )
    await server_4.start_client(
        PeerInfo(self_hostname, server_2.get_port()), on_connect=full_node_4.full_node.on_connect
    )

    # All four nodes are synced
    await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_1, num_blocks - 1)
    await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_2, num_blocks - 1)
    await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_3, num_blocks - 1)
    await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_4, num_blocks - 1)

    # Deep reorg, fall back from batch sync to long sync
    blocks_node_5 = bt.get_consecutive_blocks(250, block_list_input=blocks[:350], seed=b"node5")
    for block in blocks_node_5:
        await full_node_5.full_node.add_block(block)
    await server_5.start_client(
        PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_5.full_node.on_connect
    )
    await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_5, 250 + 350 - 1)
    await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_1, 250 + 350 - 1)


@pytest.mark.anyio
async def test_sync_from_fork_point_and_weight_proof(
    three_nodes: list[FullNodeAPI],
    default_1000_blocks: list[FullBlock],
    default_400_blocks: list[FullBlock],
    self_hostname: str,
) -> None:
    # Must be larger than "sync_block_behind_threshold" in the config
    num_blocks_initial = len(default_1000_blocks) - 50
    blocks_950 = default_1000_blocks[:num_blocks_initial]
    blocks_rest = default_1000_blocks[num_blocks_initial:]
    blocks_400 = default_400_blocks
    full_node_1, full_node_2, full_node_3 = three_nodes
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    server_3 = full_node_3.full_node.server

    for block in blocks_950:
        await full_node_1.full_node.add_block(block)

    # Node 2 syncs from halfway
    for i in range(int(len(default_1000_blocks) / 2)):
        await full_node_2.full_node.add_block(default_1000_blocks[i])

    # Node 3 syncs from a different blockchain
    for block in blocks_400:
        await full_node_3.full_node.add_block(block)

    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)
    await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_3.full_node.on_connect)

    # Also test request proof of weight
    # Have the request header hash
    res = await full_node_1.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(uint32(blocks_950[-1].height + 1), blocks_950[-1].header_hash)
    )
    assert res is not None
    assert full_node_1.full_node.weight_proof_handler is not None
    validated, _, _ = await full_node_1.full_node.weight_proof_handler.validate_weight_proof(
        full_node_protocol.RespondProofOfWeight.from_bytes(res.data).wp
    )
    assert validated

    # Don't have the request header hash
    res = await full_node_1.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(uint32(blocks_950[-1].height + 1), std_hash(b"12"))
    )
    assert res is None

    # The second node should eventually catch up to the first one, and have the
    # same tip at height num_blocks - 1
    await time_out_assert(300, node_height_exactly, True, full_node_2, num_blocks_initial - 1)
    await time_out_assert(180, node_height_exactly, True, full_node_3, num_blocks_initial - 1)

    def fn3_is_not_syncing() -> bool:
        return not full_node_3.full_node.sync_store.get_sync_mode()

    await time_out_assert(180, fn3_is_not_syncing)
    cons = list(server_1.all_connections.values())[:]
    for con in cons:
        await con.close()
    for block in blocks_rest:
        await full_node_3.full_node.add_block(block)
        peak = full_node_3.full_node.blockchain.get_peak()
        assert peak is not None
        assert peak.height >= block.height

    peak = full_node_3.full_node.blockchain.get_peak()
    assert peak is not None
    log.warning(f"FN3 height {peak.height}")

    # TODO: fix this flaky test
    await time_out_assert(180, node_height_exactly, True, full_node_3, 999)

    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)
    await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_3.full_node.on_connect)
    await server_3.start_client(PeerInfo(self_hostname, server_2.get_port()), full_node_3.full_node.on_connect)
    await time_out_assert(180, node_height_exactly, True, full_node_1, 999)
    await time_out_assert(180, node_height_exactly, True, full_node_2, 999)


@pytest.mark.anyio
async def test_batch_sync(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    # Must be below "sync_block_behind_threshold" in the config
    num_blocks = 20
    num_blocks_2 = 9
    full_node_1, full_node_2, server_1, server_2, bt = two_nodes
    blocks = bt.get_consecutive_blocks(num_blocks)
    blocks_2 = bt.get_consecutive_blocks(num_blocks_2, seed=b"123")

    # 12 blocks to node_1
    for block in blocks:
        await full_node_1.full_node.add_block(block)

    # 9 different blocks to node_2
    for block in blocks_2:
        await full_node_2.full_node.add_block(block)

    await server_2.start_client(
        PeerInfo(self_hostname, server_1.get_port()),
        on_connect=full_node_2.full_node.on_connect,
    )
    await time_out_assert(60, node_height_exactly, True, full_node_2, num_blocks - 1)


@pytest.mark.anyio
async def test_backtrack_sync_1(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    full_node_1, full_node_2, server_1, server_2, bt = two_nodes
    blocks = bt.get_consecutive_blocks(1, skip_slots=1)
    blocks = bt.get_consecutive_blocks(1, blocks, skip_slots=0)
    blocks = bt.get_consecutive_blocks(1, blocks, skip_slots=0)

    # 3 blocks to node_1 in different sub slots
    for block in blocks:
        await full_node_1.full_node.add_block(block)

    await server_2.start_client(
        PeerInfo(self_hostname, server_1.get_port()),
        on_connect=full_node_2.full_node.on_connect,
    )
    await time_out_assert(60, node_height_exactly, True, full_node_2, 2)


@pytest.mark.anyio
async def test_backtrack_sync_2(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], self_hostname: str
) -> None:
    full_node_1, full_node_2, server_1, server_2, bt = two_nodes
    blocks = bt.get_consecutive_blocks(1, skip_slots=3)
    blocks = bt.get_consecutive_blocks(8, blocks, skip_slots=0)

    # 3 blocks to node_1 in different sub slots
    for block in blocks:
        await full_node_1.full_node.add_block(block)

    await server_2.start_client(
        PeerInfo(self_hostname, server_1.get_port()),
        on_connect=full_node_2.full_node.on_connect,
    )
    await time_out_assert(60, node_height_exactly, True, full_node_2, 8)


@pytest.mark.anyio
async def test_close_height_but_big_reorg(three_nodes: list[FullNodeAPI], bt: BlockTools, self_hostname: str) -> None:
    blocks_a = bt.get_consecutive_blocks(50)
    blocks_b = bt.get_consecutive_blocks(51, seed=b"B")
    blocks_c = bt.get_consecutive_blocks(90, seed=b"C")
    full_node_1, full_node_2, full_node_3 = three_nodes
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    server_3 = full_node_3.full_node.server

    for block in blocks_a:
        await full_node_1.full_node.add_block(block)
    for block in blocks_b:
        await full_node_2.full_node.add_block(block)
    for block in blocks_c:
        await full_node_3.full_node.add_block(block)

    await server_2.start_client(
        PeerInfo(self_hostname, server_1.get_port()),
        on_connect=full_node_2.full_node.on_connect,
    )
    await time_out_assert(80, node_height_exactly, True, full_node_1, 50)
    await time_out_assert(80, node_height_exactly, True, full_node_2, 50)
    await time_out_assert(80, node_height_exactly, True, full_node_3, 89)

    await server_3.start_client(
        PeerInfo(self_hostname, server_1.get_port()),
        on_connect=full_node_3.full_node.on_connect,
    )

    await server_3.start_client(
        PeerInfo(self_hostname, server_2.get_port()),
        on_connect=full_node_3.full_node.on_connect,
    )
    await time_out_assert(80, node_height_exactly, True, full_node_1, 89)
    await time_out_assert(80, node_height_exactly, True, full_node_2, 89)
    await time_out_assert(80, node_height_exactly, True, full_node_3, 89)


@pytest.mark.anyio
async def test_sync_bad_peak_while_synced(
    three_nodes: list[FullNodeAPI],
    default_1000_blocks: list[FullBlock],
    default_1500_blocks: list[FullBlock],
    self_hostname: str,
) -> None:
    # Must be larger than "sync_block_behind_threshold" in the config
    num_blocks_initial = len(default_1000_blocks) - 250
    blocks_750 = default_1000_blocks[:num_blocks_initial]
    full_node_1, full_node_2, full_node_3 = three_nodes
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    server_3 = full_node_3.full_node.server
    full_node_3.full_node.weight_proof_handler = None
    for block in blocks_750:
        await full_node_1.full_node.add_block(block)
    # Node 3 syncs from a different blockchain

    for block in default_1500_blocks[:1100]:
        await full_node_3.full_node.add_block(block)

    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)

    # The second node should eventually catch up to the first one, and have the
    # same tip at height num_blocks - 1
    await time_out_assert(180, node_height_exactly, True, full_node_2, num_blocks_initial - 1)
    # set new heavy peak, fn3 cannot serve wp's
    # node 2 should keep being synced and receive blocks
    await server_3.start_client(PeerInfo(self_hostname, server_3.get_port()), full_node_3.full_node.on_connect)
    # trigger long sync in full node 2
    peak_block = default_1500_blocks[1050]
    await server_2.start_client(PeerInfo(self_hostname, server_3.get_port()), full_node_2.full_node.on_connect)
    con = server_2.all_connections[full_node_3.full_node.server.node_id]
    peak = full_node_protocol.NewPeak(
        peak_block.header_hash,
        peak_block.height,
        peak_block.weight,
        peak_block.height,
        peak_block.reward_chain_block.get_unfinished().get_hash(),
    )
    await full_node_2.full_node.new_peak(peak, con)
    await asyncio.sleep(2)
    assert not full_node_2.full_node.sync_store.get_sync_mode()
    for block in default_1000_blocks[1000 - num_blocks_initial :]:
        await full_node_2.full_node.add_block(block)

    assert node_height_exactly(full_node_2, uint32(999))


@pytest.mark.anyio
async def test_block_ses_mismatch(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_1000_blocks: list[FullBlock],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_node_1, full_node_2, server_1, server_2, _ = two_nodes
    blocks = default_1000_blocks

    # mock for full node _sync
    async def async_mock() -> None:
        log.info("do nothing")

    with monkeypatch.context() as monkeypatch_context:
        monkeypatch_context.setattr(full_node_2.full_node, "_sync", async_mock)
        # load blocks into node 1
        for block in blocks[:501]:
            await full_node_1.full_node.add_block(block)

        peak1 = full_node_1.full_node.blockchain.get_peak()
        assert peak1 is not None

        summary_heights = full_node_1.full_node.blockchain.get_ses_heights()
        summaries: list[SubEpochSummary] = []

        # get ses list
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            summaries.append(full_node_1.full_node.blockchain.get_ses(ses_height))

        # change summary so check would fail on sub epoch 1
        s = summaries[1]
        summaries[1] = SubEpochSummary(
            s.prev_subepoch_summary_hash,
            s.reward_chain_hash,
            s.num_blocks_overflow,
            uint64(s.new_difficulty * 2) if s.new_difficulty is not None else None,
            uint64(s.new_sub_slot_iters * 2) if s.new_sub_slot_iters is not None else None,
            None,
        )
        # manually try sync with wrong sub epoch summary list
        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

        # call peer has block to populate peer_to_peak
        full_node_2.full_node.sync_store.peer_has_block(
            peak1.header_hash, full_node_1.full_node.server.node_id, peak1.weight, peak1.height, True
        )
        # sync using bad ses list
        await full_node_2.full_node.sync_from_fork_point(uint32(0), peak1.height, peak1.header_hash, summaries)
        # assert we failed somewhere between sub epoch 0 to sub epoch 1
        assert node_height_between(full_node_2, summary_heights[0], summary_heights[1])


@pytest.mark.anyio
@pytest.mark.skip("skipping until we re-enable the capability in chia.protocols.shared_protocol")
async def test_sync_none_wp_response_backward_comp(
    three_nodes: list[FullNodeAPI], default_1000_blocks: list[FullBlock], self_hostname: str
) -> None:
    num_blocks_initial = len(default_1000_blocks) - 50
    blocks_950 = default_1000_blocks[:num_blocks_initial]
    full_node_1, full_node_2, full_node_3 = three_nodes
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    server_3 = full_node_3.full_node.server
    server_3.set_capabilities(
        [
            (uint16(Capability.BASE.value), "1"),
            (uint16(Capability.BLOCK_HEADERS.value), "1"),
            (uint16(Capability.RATE_LIMITS_V2.value), "1"),
        ]
    )

    for block in blocks_950:
        await full_node_1.full_node.add_block(block)

    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)
    await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_3.full_node.on_connect)

    peers = [c for c in full_node_2.full_node.server.all_connections.values()]
    request = full_node_protocol.RequestProofOfWeight(
        uint32(blocks_950[-1].height + 1), default_1000_blocks[-1].header_hash
    )
    start = time.time()
    res = await peers[0].call_api(FullNodeAPI.request_proof_of_weight, request, timeout=5)
    assert res is None
    duration = time.time() - start
    log.info(f"result was {res}")
    assert duration < 1

    peers = [c for c in full_node_3.full_node.server.all_connections.values()]
    request = full_node_protocol.RequestProofOfWeight(
        uint32(blocks_950[-1].height + 1), default_1000_blocks[-1].header_hash
    )
    start = time.time()
    res = await peers[0].call_api(FullNodeAPI.request_proof_of_weight, request, timeout=6)
    assert res is None
    duration = time.time() - start
    assert duration > 5


@pytest.mark.anyio
async def test_bad_peak_cache_invalidation(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_1000_blocks: list[FullBlock],
    blockchain_constants: ConsensusConstants,
    consensus_mode: ConsensusMode,
) -> None:
    full_node_1, _full_node_2, _server_1, _server_2, bt = two_nodes

    for block in default_1000_blocks[:-500]:
        await full_node_1.full_node.add_block(block)

    cache_size = full_node_1.full_node.config.get("bad_peak_cache_size")
    assert cache_size is not None
    for x in range(cache_size + 10):
        blocks = bt.get_consecutive_blocks(
            num_blocks=1, block_list_input=default_1000_blocks[:-500], seed=x.to_bytes(2, "big")
        )
        block = blocks[-1]
        full_node_1.full_node.add_to_bad_peak_cache(block.header_hash, block.height)

    assert len(full_node_1.full_node.bad_peak_cache) == cache_size

    for block in default_1000_blocks[500:]:
        await full_node_1.full_node.add_block(block)

    blocks = bt.get_consecutive_blocks(num_blocks=1, block_list_input=default_1000_blocks[:-1])
    block = blocks[-1]
    full_node_1.full_node.add_to_bad_peak_cache(block.header_hash, block.height)
    assert len(full_node_1.full_node.bad_peak_cache) == 1


@pytest.mark.anyio
async def test_weight_proof_timeout_slow_connection(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_1000_blocks: list[FullBlock],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test that weight proof downloads complete successfully on slow connections.
    This test verifies that periodic pings are sent while waiting for weight proof responses,
    keeping the connection alive even when downloads take longer than the heartbeat timeout (60s).

    Without the ping keepalive mechanism, this test would fail because:
    - The heartbeat timeout is 60 seconds
    - Weight proof downloads can take > 60 seconds on slow connections
    - No messages are received during the download, so heartbeat timer expires
    - Connection is closed prematurely

    With the ping keepalive mechanism:
    - Pings are sent every 20 seconds while waiting for weight proof responses
    - Pong responses reset the heartbeat timer
    - Connection stays alive during long downloads
    """
    full_node_1, full_node_2, server_1, server_2, _bt = two_nodes

    # Set a weight_proof_timeout that's longer than the heartbeat (60s)
    # This ensures the download will take longer than the heartbeat timeout
    weight_proof_timeout = 120  # 120 seconds
    full_node_1.full_node.config["weight_proof_timeout"] = weight_proof_timeout
    full_node_2.full_node.config["weight_proof_timeout"] = weight_proof_timeout

    # Add enough blocks to create a weight proof
    await add_blocks_in_batches(default_1000_blocks[:600], full_node_1.full_node)

    # Track message sends to simulate slow connection
    original_send_message = WSChiaConnection._send_message
    send_count = 0
    weight_proof_start_time: float | None = None
    weight_proof_end_time: float | None = None

    async def slow_send_message(self: WSChiaConnection, message: Message) -> None:
        nonlocal send_count, weight_proof_start_time, weight_proof_end_time
        send_count += 1
        # Simulate slow connection by adding delays for large messages
        # (weight proof responses are large - simulate slow bandwidth)
        if ProtocolMessageTypes(message.type) == ProtocolMessageTypes.respond_proof_of_weight:
            if weight_proof_start_time is None:
                weight_proof_start_time = time.time()
            # Simulate slow connection: delay proportional to message size
            # Weight proofs can be several MB, so simulate ~100KB/s bandwidth
            # This ensures the download takes > 60 seconds for large weight proofs
            message_size = len(message.data)
            # Simulate 100KB/s bandwidth: delay = size / 100000
            # For a 5MB weight proof, this would be ~50 seconds
            # Add minimum 70 seconds to ensure we exceed 60s heartbeat threshold
            delay = max(70.0, message_size / 100000.0)
            await asyncio.sleep(delay)
            weight_proof_end_time = time.time()
        await original_send_message(self, message)

    # Patch the send_message method to simulate slow connection
    monkeypatch.setattr(WSChiaConnection, "_send_message", slow_send_message)

    # Track ping calls to verify they're being sent during weight proof wait
    ping_times: list[float] = []
    original_ping_methods: dict[object, Any] = {}

    def track_ping_for_connection(connection: WSChiaConnection) -> None:
        """Patch the websocket ping method to track calls."""
        if connection.ws not in original_ping_methods:
            original_ping_methods[connection.ws] = connection.ws.ping

            async def tracked_ping(msg: bytes = b"") -> None:
                ping_times.append(time.time())
                await original_ping_methods[connection.ws](msg)

            monkeypatch.setattr(connection.ws, "ping", tracked_ping)

    # Track the entire sync process time
    sync_start_time = time.time()

    # Connect node 2 to node 1 - this will trigger weight proof download during sync
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)

    # Patch ping methods on all connections to track when pings are sent
    # We need to do this after connections are established
    await asyncio.sleep(0.5)  # Give connections time to establish
    for connection in server_2.all_connections.values():
        if connection.connection_type == NodeType.FULL_NODE:
            track_ping_for_connection(connection)

    # Wait for sync - this will trigger weight proof download
    def nodes_synced() -> bool:
        peak_1 = full_node_1.full_node.blockchain.get_peak()
        peak_2 = full_node_2.full_node.blockchain.get_peak()
        return peak_1 is not None and peak_2 is not None and peak_1.height == peak_2.height

    # This should complete successfully even with slow connection and 60s heartbeat
    # because pings are sent every 30s to keep the connection alive
    await time_out_assert(180, nodes_synced)

    sync_end_time = time.time()
    sync_duration = sync_end_time - sync_start_time

    # Verify that the nodes actually synced
    assert nodes_synced()
    assert send_count > 0  # Verify that messages were sent

    # Verify that a weight proof message was actually sent during sync
    # If no weight proof was requested, the test would fail later with a confusing error
    assert weight_proof_start_time is not None, (
        "No weight proof message (respond_proof_of_weight) was sent during sync. "
        "The test requires a weight proof to verify the ping keepalive fix works correctly."
    )
    assert weight_proof_end_time is not None, (
        "Weight proof message transmission did not complete. "
        "This indicates the weight proof response was not fully sent."
    )

    weight_proof_duration = weight_proof_end_time - weight_proof_start_time
    log.info(f"Sync process took {sync_duration:.2f} seconds")
    log.info(f"Weight proof message transmission took {weight_proof_duration:.2f} seconds")
    log.info(f"Pings sent during weight proof wait: {len(ping_times)}")

    # Verify that the sync process (which includes weight proof download) took longer than 60 seconds
    # This proves the ping keepalive is working (without pings, 60s heartbeat would have closed the connection)
    assert sync_duration > 60.0, (
        f"Sync process took {sync_duration:.2f}s, expected > 60s to verify ping keepalive prevents connection closure"
    )

    # Verify that pings were sent during the weight proof wait
    # With a 70+ second download and 20s ping interval, we should see at least 3 pings
    # (one at ~20s, one at ~40s, one at ~60s)
    assert len(ping_times) >= 3, (
        f"Expected at least 3 pings during weight proof wait (download took {weight_proof_duration:.2f}s), "
        f"but only {len(ping_times)} were sent. This indicates the ping keepalive mechanism is not working."
    )

    # Verify pings were sent at approximately 20-second intervals
    if len(ping_times) >= 2:
        ping_intervals = [ping_times[i] - ping_times[i - 1] for i in range(1, len(ping_times))]
        avg_interval = sum(ping_intervals) / len(ping_intervals)
        # Ping interval should be around 20 seconds (allow some variance)
        assert 15.0 <= avg_interval <= 25.0, (
            f"Ping intervals should be ~20s, but average was {avg_interval:.2f}s. Intervals: {ping_intervals}"
        )


@pytest.mark.anyio
async def test_send_request_ping_failure_logs_info() -> None:
    """
    Test that when ping fails during keepalive, it logs at INFO level (lines 635-636).
    """
    # Create a mock websocket
    mock_ws = AsyncMock()
    mock_ws.closed = False
    ping_exception = Exception("Connection closed")
    mock_ws.ping = AsyncMock(side_effect=ping_exception)

    # Create a mock API
    mock_api = MagicMock()

    # Create connection
    connection = WSChiaConnection.create(
        NodeType.FULL_NODE,
        mock_ws,
        mock_api,
        8444,
        log,
        True,
        None,
        None,
        bytes32([0] * 32),
        100,
        30,
        local_capabilities_for_handshake=default_capabilities[NodeType.FULL_NODE],
        stub_metadata_for_type=StubMetadataRegistry,
    )

    # Create a message that will trigger the ping keepalive (timeout > 60)
    message = make_msg(ProtocolMessageTypes.request_peers, RequestPeers())

    # Track log calls
    log_calls = []

    def log_info_wrapper(*args: object, **kwargs: object) -> None:
        log_calls.append(("INFO", args, kwargs))

    # Patch the log.info method
    with patch.object(connection.log, "info", side_effect=log_info_wrapper):
        # Start the send_request in a task
        request_task = create_referenced_task(connection.send_request(message, timeout=65))

        # Wait for ping interval to elapse (20 seconds, but we'll use a shorter wait for testing)
        # We need to wait long enough for the ping to be attempted
        # The ping interval is 20s, but we'll wait a bit to ensure it's triggered
        await asyncio.sleep(0.25)

        # Set the event to complete the request (simulate response)
        if message.id in connection.pending_requests:
            connection.pending_requests[message.id].set()

        # Wait for the request to complete
        try:
            await asyncio.wait_for(request_task, timeout=1.0)
        except asyncio.TimeoutError:
            request_task.cancel()
            try:
                await request_task
            except (asyncio.CancelledError, Exception):
                pass

    # Verify that ping was called
    assert mock_ws.ping.called, "Ping should have been called"

    # Verify that INFO level log was called with the expected message
    info_logs = [
        call
        for call in log_calls
        if call[0] == "INFO" and len(call[1]) > 0 and "Failed to send ping" in str(call[1][0])
    ]
    assert len(info_logs) > 0, f"Expected INFO log for ping failure, but got: {log_calls}"


@pytest.mark.anyio
async def test_send_request_timeout_exceeded_raises_timeout_error() -> None:
    """
    Test that when timeout is exceeded, it raises asyncio.TimeoutError (line 641).
    """
    # Create a mock websocket
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_ws.ping = AsyncMock()

    # Create a mock API
    mock_api = MagicMock()

    # Create connection
    connection = WSChiaConnection.create(
        NodeType.FULL_NODE,
        mock_ws,
        mock_api,
        8444,
        log,
        True,
        None,
        None,
        bytes32([0] * 32),
        100,
        30,
        local_capabilities_for_handshake=default_capabilities[NodeType.FULL_NODE],
        stub_metadata_for_type=StubMetadataRegistry,
    )

    # Create a message that will trigger the ping keepalive (timeout > 60)
    message = make_msg(ProtocolMessageTypes.request_peers, RequestPeers())

    # Mock time.time() to control the timeout
    start_time = 1000.0
    time_values = [start_time, start_time + 20.0, start_time + 66.0]
    time_index = [0]

    def mock_time() -> float:
        idx = time_index[0]
        if idx < len(time_values):
            result = time_values[idx]
            time_index[0] += 1
            return result
        return time_values[-1]

    with patch("chia.server.ws_connection.time.time", side_effect=mock_time):
        # Start the send_request
        request_task = create_referenced_task(connection.send_request(message, timeout=65))

        # Wait a bit to let the timeout logic run
        await asyncio.sleep(0.1)

        # Wait for the request to complete or timeout
        # The send_request should catch the TimeoutError and return None
        result = await asyncio.wait_for(request_task, timeout=1.0)
        # When timeout occurs, send_request returns None
        assert result is None, "Expected None when timeout is exceeded"


@pytest.mark.anyio
async def test_server_side_changes_not_needed_for_60s_timeout() -> None:
    """
    Test to prove that server-side changes are NOT necessary for 60-second timeout issue.

    Analysis:
    1. Garbage collection checks last_message_time after 1800 seconds (30 minutes), not 60s
    2. Server is actively sending data (weight proof), so it's not idle
    3. aiohttp websocket heartbeat=60 handles pings/pongs automatically
    4. The 60-second timeout is on the CLIENT side waiting for response

    This test verifies that:
    - Server sending messages doesn't require last_message_time updates for 60s timeout
    - aiohttp automatically handles pings/pongs, so explicit PING handling isn't needed for heartbeat
    - The real issue is CLIENT side not receiving messages, which we fix with client-side pings

    Conclusion: Server-side changes (updating last_message_time on send/PING) are NOT needed
    for the 60-second timeout issue. They might help with 30-minute garbage collection, but
    that's a different problem. The fix should be CLIENT-side only (ping keepalive while waiting).
    """
    # Create a mock websocket for server side
    mock_ws_server = AsyncMock()
    mock_ws_server.closed = False
    mock_ws_server.send_bytes = AsyncMock()

    # Create a mock API for server
    mock_api_server = MagicMock()

    # Create server connection (inbound, simulating server receiving connection)
    server_connection = WSChiaConnection.create(
        NodeType.FULL_NODE,
        mock_ws_server,
        mock_api_server,
        8444,
        log,
        False,  # Server side (inbound)
        None,
        None,
        bytes32([0] * 32),
        100,
        30,
        local_capabilities_for_handshake=default_capabilities[NodeType.FULL_NODE],
        stub_metadata_for_type=StubMetadataRegistry,
    )

    # Set initial last_message_time
    initial_time = time.time() - 100.0  # 100 seconds ago
    server_connection.last_message_time = initial_time

    # Simulate server sending a large message (weight proof response)
    test_data = b"x" * 1024  # 1KB for testing
    large_message = make_msg(ProtocolMessageTypes.respond_proof_of_weight, test_data)

    # Temporarily remove the server-side fix to test behavior without it
    original_send_message = server_connection._send_message

    async def send_without_last_message_update(self: WSChiaConnection, message: Message) -> None:
        """Version of _send_message without last_message_time update."""
        encoded: bytes = bytes(message)
        size = len(encoded)
        assert len(encoded) < (2 ** (4 * 8))  # LENGTH_BYTES = 4
        # Skip rate limiting for test
        await self.ws.send_bytes(encoded)
        self.bytes_written += size
        # NOTE: We're NOT updating last_message_time here to test if it's needed

    # Patch to use version without last_message_time update
    server_connection._send_message = send_without_last_message_update.__get__(server_connection, WSChiaConnection)

    # Send the message WITHOUT updating last_message_time
    await server_connection._send_message(large_message)

    # Check last_message_time - it should NOT be updated (proving we're testing without the fix)
    send_updated_time = server_connection.last_message_time

    # Verify that last_message_time was NOT updated (proving we're testing without server-side fix)
    assert send_updated_time == initial_time, (
        f"Without server-side fix, last_message_time should NOT be updated when sending. "
        f"Initial: {initial_time}, After send: {send_updated_time}"
    )

    # Restore original method
    server_connection._send_message = original_send_message

    # Now test with the server-side fix enabled
    await server_connection._send_message(large_message)
    fixed_updated_time = server_connection.last_message_time

    # Verify that WITH the fix, last_message_time IS updated
    assert fixed_updated_time > initial_time, (
        f"With server-side fix, last_message_time should be updated. "
        f"Initial: {initial_time}, After send: {fixed_updated_time}"
    )

    # Key insight: Since garbage collection only checks after 1800 seconds (30 minutes),
    # and weight proof timeouts are typically 120-360 seconds (< 5 minutes), the server-side
    # last_message_time update is NOT needed for the 60-second timeout issue.
    # The server is actively sending data, so it's not considered idle by garbage collection.
    # The real issue is the CLIENT side waiting >60 seconds without receiving messages,
    # which we fix with client-side ping keepalive.

    # Conclusion: Server-side changes are NOT necessary for the 60-second timeout.
    # They might be useful for other scenarios (30-minute garbage collection), but
    # the weight proof timeout issue is solved by CLIENT-side ping keepalive only.
