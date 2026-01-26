from __future__ import annotations

import asyncio
import logging
import time

import pytest
from chia_rs import ConsensusConstants, FullBlock, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia._tests.conftest import ConsensusMode
from chia._tests.core.node_height import node_height_between, node_height_exactly
from chia._tests.util.tcp_proxy import tcp_proxy
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.protocols.shared_protocol import Capability
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.types.peer_info import PeerInfo
from chia.util.hash import std_hash

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


# Configuration: Which consensus mode(s) to run this test on.
# This test is resource-intensive (creates TCP proxy, builds large chain, slow network simulation),
# so by default we only run it on the newest consensus mode to save time and resources.
# To run on all consensus modes, change this to:
#   [ConsensusMode.PLAIN, ConsensusMode.HARD_FORK_2_0, ConsensusMode.SOFT_FORK_2_6]
# To run on a specific mode, use: [ConsensusMode.PLAIN] or [ConsensusMode.HARD_FORK_2_0], etc.
ALLOWED_CONSENSUS_MODES_FOR_SLOW_WP_TEST = [ConsensusMode.SOFT_FORK_2_6]


async def _request_weight_proof_through_proxy(
    server_1: ChiaServer,
    server_2: ChiaServer,
    self_hostname: str,
    peak_height: int,
    peak_header_hash: bytes32,
    bandwidth_bytes_per_sec: int,
) -> tuple[full_node_protocol.RespondProofOfWeight | None, float, str | None]:
    """
    Helper to request a weight proof through a throttled TCP proxy.

    Returns:
        tuple of (response, download_time, error_message)
        - response is the RespondProofOfWeight if successful, None if failed
        - download_time is the time taken (or time until failure)
        - error_message is None if successful, otherwise describes the failure
    """
    server_1_port = server_1.get_port()

    async with tcp_proxy(
        listen_host="127.0.0.1",
        listen_port=0,
        server_host=self_hostname,
        server_port=server_1_port,
        upload_bytes_per_sec=bandwidth_bytes_per_sec,
        download_bytes_per_sec=bandwidth_bytes_per_sec,
    ) as proxy:
        proxy_port = proxy.proxy_port
        bandwidth_mbps = bandwidth_bytes_per_sec * 8 / 1_000_000
        log.info(
            f"TCP proxy listening on port {proxy_port} at "
            f"{bandwidth_bytes_per_sec:,} bytes/sec ({bandwidth_mbps:.1f} Mbps)"
        )

        # Connect through the proxy
        log.info(f"Connecting to proxy port {proxy_port}...")
        connected = await server_2.start_client(PeerInfo(self_hostname, proxy_port))
        log.info(f"start_client returned: {connected}")
        if not connected:
            return None, 0.0, "Failed to connect through proxy"

        # Find our specific connection by matching the proxy port
        # This allows multiple parallel connections through different proxies
        log.info(f"Looking for connection to proxy port {proxy_port}")
        log.info(f"Available connections: {list(server_2.all_connections.keys())}")
        connection = None
        for conn in server_2.all_connections.values():
            peer_port = conn.peer_info.port if conn.peer_info is not None else None
            log.info(f"  Connection {conn.peer_node_id}: peer_info.port={peer_port}")
            if conn.peer_info is not None and conn.peer_info.port == proxy_port:
                connection = conn
                break
        if connection is None:
            return None, 0.0, f"No connection found to proxy port {proxy_port}"

        log.info("Found connection, requesting weight proof...")

        # Request the weight proof (uses project default timeout)
        request = full_node_protocol.RequestProofOfWeight(uint32(peak_height + 1), peak_header_hash)

        start_time = time.time()
        try:
            wp_response = await connection.call_api(
                FullNodeAPI.request_proof_of_weight,
                request,
            )
            download_time = time.time() - start_time

            # Close connection immediately after receiving response to prevent
            # background sync from continuing and stalling the test
            await connection.close()

            if wp_response is None:
                # call_api returns None when the websocket times out waiting for a response
                # (the timeout is handled internally and doesn't raise an exception)
                return None, download_time, "Weight proof response was None (websocket timeout)"

            return wp_response, download_time, None

        except asyncio.TimeoutError:
            # This branch is unlikely to be hit since call_api handles timeout internally,
            # but we keep it for safety in case of other async operations timing out
            download_time = time.time() - start_time
            await connection.close()
            return None, download_time, f"Timeout after {download_time:.2f}s"
        except Exception as e:
            download_time = time.time() - start_time
            await connection.close()
            return None, download_time, f"Error: {type(e).__name__}: {e}"


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(
    allowed=ALLOWED_CONSENSUS_MODES_FOR_SLOW_WP_TEST,
    reason="Test is resource-intensive; by default only runs on newest consensus mode.",
)
async def test_slow_weight_proof_download(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_2000_blocks_compact: list[FullBlock],
    self_hostname: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Test weight proof download over throttled network connections.

    This test uses a TCP proxy to simulate slow network conditions between two full nodes.
    It validates that large messages (weight proofs) can be transferred correctly over
    bandwidth-limited connections.

    The TCP proxy (chia/_tests/util/tcp_proxy.py) is a reusable utility that can throttle
    any TCP traffic between nodes. It can be used to validate various network-related
    improvements including:

    1. CHUNKED/STREAMING RESPONSES: If the websocket library is modified to send large
       messages in chunks rather than as a single message, this test would verify that
       all chunks arrive correctly and reassemble into a valid weight proof.

    2. PROGRESS-BASED TIMEOUT RESET: If the library implements timeout reset on data
       received (rather than a fixed timeout from request start), slower connections
       would succeed as long as data keeps flowing. Adjust SLOW_BANDWIDTH_BYTES_PER_SEC
       to test the boundary conditions.

    3. HEARTBEAT/KEEPALIVE CHANGES: The proxy maintains the TCP connection while
       throttling data, allowing testing of how heartbeat mechanisms interact with
       slow data transfer.

    Configuration (adjust these to test different scenarios):
    - FAST_BANDWIDTH_BYTES_PER_SEC: Bandwidth where transfer should complete within default timeout
    - SLOW_BANDWIDTH_BYTES_PER_SEC: Bandwidth where transfer behavior depends on implementation

    Current behavior (before websocket improvements):
    - Weight proof is sent as a single websocket message
    - call_api() uses asyncio.wait_for() with the project's default timeout (60s)
    - If the entire message doesn't arrive within timeout, the request fails

    After implementing streaming/chunked responses:
    - The slow bandwidth test should pass if timeout resets on each chunk received
    - Download time will match expected time (message_size / bandwidth)
    """
    # ============================================================
    # TEST CONFIGURATION
    # Adjust these values to test different scenarios
    # ============================================================

    # Fast bandwidth: should always succeed (transfer time < default 60s timeout)
    # 1.5 Mbps = 187,500 bytes/sec -> ~11s for 2 MB
    # Note: 1.5 Mbps is equivalent to a T-1 line speed
    FAST_BANDWIDTH_BYTES_PER_SEC = 187_500

    # Slow bandwidth: tests timeout behavior under constrained conditions
    # 0.2 Mbps = 25,000 bytes/sec -> ~81s for 2 MB
    # This speed is intentionally set to require ~80 seconds for the weight proof
    # download. We use a shorter chain (2000 blocks) with a smaller weight proof
    # (~2 MB) for testing efficiency, while still ensuring the transfer time
    # exceeds the 60s default timeout to trigger the timeout behavior.
    # After implementing progress-based timeouts, this should succeed.
    SLOW_BANDWIDTH_BYTES_PER_SEC = 25_000

    # ============================================================
    # TEST SETUP
    # ============================================================
    # Use two nodes:
    # - full_node_1: Server node with blocks
    # - full_node_2: Client node for both tests (cleaned up between tests)
    full_node_1, full_node_2, server_1, server_2, _bt = two_nodes

    # Use cached blocks (generated once and persisted to disk)
    blocks = default_2000_blocks_compact
    num_blocks = len(blocks)

    log.info(f"Using {num_blocks} cached blocks")

    # Add blocks to node 1 (the server)
    start_time = time.time()
    for block in blocks:
        await full_node_1.full_node.add_block(block)
    add_blocks_time = time.time() - start_time
    log.info(f"Added {num_blocks} blocks to node 1 in {add_blocks_time:.2f} seconds")

    # Verify node 1 has the blocks
    peak_1 = full_node_1.full_node.blockchain.get_peak()
    assert peak_1 is not None
    assert peak_1.height == num_blocks - 1
    log.info(f"Node 1 peak height: {peak_1.height}")

    # Get the weight proof to check its size
    start_time = time.time()
    assert full_node_1.full_node.weight_proof_handler is not None
    weight_proof = await full_node_1.full_node.weight_proof_handler.get_proof_of_weight(peak_1.header_hash)
    create_wp_time = time.time() - start_time
    assert weight_proof is not None, "Failed to create weight proof"
    log.info(f"Weight proof created in {create_wp_time:.2f}s")

    # Serialize the weight proof to get its actual size
    wp_message = full_node_protocol.RespondProofOfWeight(weight_proof, peak_1.header_hash)
    wp_bytes = bytes(wp_message)
    actual_wp_size = len(wp_bytes)
    wp_size_mb = actual_wp_size / 1024 / 1024

    # Verify weight proof is large enough for this test to be meaningful
    # If weight proofs get smaller in the future, the bandwidth/timeout values in this
    # test will need to be adjusted to still trigger the timeout behavior we're testing.
    MIN_WEIGHT_PROOF_SIZE_MB = 1.8
    assert wp_size_mb > MIN_WEIGHT_PROOF_SIZE_MB, (
        f"Weight proof size ({wp_size_mb:.2f} MB) is smaller than expected ({MIN_WEIGHT_PROOF_SIZE_MB} MB). "
        f"If weight proofs have gotten smaller, adjust FAST_BANDWIDTH_BYTES_PER_SEC and "
        f"SLOW_BANDWIDTH_BYTES_PER_SEC to ensure TEST 1 completes within the 60 second timeout and "
        f"TEST 2 exceeds the timeout of 60 seconds."
    )

    # Calculate expected transfer times and Mbps values
    expected_time_fast = actual_wp_size / FAST_BANDWIDTH_BYTES_PER_SEC
    expected_time_slow = actual_wp_size / SLOW_BANDWIDTH_BYTES_PER_SEC
    fast_mbps = FAST_BANDWIDTH_BYTES_PER_SEC * 8 / 1_000_000
    slow_mbps = SLOW_BANDWIDTH_BYTES_PER_SEC * 8 / 1_000_000

    log.info(f"Weight proof size: {actual_wp_size:,} bytes ({wp_size_mb:.2f} MB)")
    log.info(
        f"Fast bandwidth: {FAST_BANDWIDTH_BYTES_PER_SEC:,} bytes/sec ({fast_mbps:.1f} Mbps) "
        f"-> expected {expected_time_fast:.1f}s"
    )
    log.info(
        f"Slow bandwidth: {SLOW_BANDWIDTH_BYTES_PER_SEC:,} bytes/sec ({slow_mbps:.1f} Mbps) "
        f"-> expected {expected_time_slow:.1f}s"
    )

    # ============================================================
    # TEST 1: FAST BANDWIDTH (should succeed)
    # This test verifies basic functionality - the proxy correctly
    # forwards data and the weight proof transfers successfully
    # when bandwidth is sufficient to complete within the default timeout.
    # ============================================================
    log.info("=" * 60)
    log.info("TEST 1: Weight proof download at fast bandwidth (should succeed)")
    log.info(f"  Bandwidth: {FAST_BANDWIDTH_BYTES_PER_SEC:,} bytes/sec ({fast_mbps:.1f} Mbps)")
    log.info(f"  Expected time: {expected_time_fast:.1f}s")
    log.info("=" * 60)

    wp_response_1, download_time_1, error_1 = await _request_weight_proof_through_proxy(
        server_1=server_1,
        server_2=server_2,
        self_hostname=self_hostname,
        peak_height=peak_1.height,
        peak_header_hash=peak_1.header_hash,
        bandwidth_bytes_per_sec=FAST_BANDWIDTH_BYTES_PER_SEC,
    )

    log.info(f"TEST 1 Result: download_time={download_time_1:.2f}s, error={error_1}")

    assert error_1 is None, f"TEST 1 FAILED: {error_1}"
    assert wp_response_1 is not None, "TEST 1 FAILED: No response"
    assert isinstance(wp_response_1, full_node_protocol.RespondProofOfWeight)
    assert wp_response_1.wp is not None

    # Validate the weight proof
    assert full_node_2.full_node.weight_proof_handler is not None
    validated, val_error, _fork_point = await full_node_2.full_node.weight_proof_handler.validate_weight_proof(
        wp_response_1.wp
    )
    assert validated, f"TEST 1 weight proof validation failed: {val_error}"

    log.info(f"TEST 1 PASSED: Downloaded and validated in {download_time_1:.2f} seconds")

    # Clean up connections from TEST 1 before starting TEST 2
    # This ensures server_1 is ready to accept a new connection from server_3
    await server_2.close_all_connections()
    await server_1.close_all_connections()

    # ============================================================
    # TEST 2: SLOW BANDWIDTH (behavior depends on implementation)
    # Reuses full_node_2 after cleaning up connections from TEST 1.
    #
    # This test exercises the timeout behavior under constrained
    # network conditions. The expected outcome depends on how
    # timeouts are implemented:
    #
    # - FIXED TIMEOUT (current): Will fail if expected_time > default timeout
    # - PROGRESS-BASED TIMEOUT: Will succeed as long as data flows
    # - CHUNKED TRANSFER: May succeed with per-chunk timeouts
    #
    # Adjust SLOW_BANDWIDTH_BYTES_PER_SEC to test boundary conditions.
    # ============================================================
    log.info("=" * 60)
    log.info("TEST 2: Weight proof download at slow bandwidth")
    log.info(f"  Bandwidth: {SLOW_BANDWIDTH_BYTES_PER_SEC:,} bytes/sec ({slow_mbps:.1f} Mbps)")
    log.info(f"  Expected time: {expected_time_slow:.1f}s")
    log.info("=" * 60)

    wp_response_2, download_time_2, error_2 = await _request_weight_proof_through_proxy(
        server_1=server_1,
        server_2=server_2,
        self_hostname=self_hostname,
        peak_height=peak_1.height,
        peak_header_hash=peak_1.header_hash,
        bandwidth_bytes_per_sec=SLOW_BANDWIDTH_BYTES_PER_SEC,
    )

    log.info(f"TEST 2 Result: download_time={download_time_2:.2f}s, error={error_2}")

    # Check if the RuntimeError about weight proof timeout appears in the logs
    # This error comes from full_node.py when the weight proof doesn't arrive in time
    runtime_error_in_logs = any(
        "Weight proof did not arrive in time from peer" in record.message for record in caplog.records
    )

    # ============================================================
    # Summary
    # ============================================================
    log.info("=" * 60)
    log.info("SUMMARY:")
    log.info(f"  Weight proof size:       {actual_wp_size:,} bytes ({wp_size_mb:.2f} MB)")
    log.info(f"  TEST 1 (fast):           {download_time_1:.2f}s - PASSED")
    if error_2 is None:
        log.info(f"  TEST 2 (slow):           {download_time_2:.2f}s - PASSED")
    else:
        log.info(f"  TEST 2 (slow):           {download_time_2:.2f}s - FAILED ({error_2})")
    log.info(f"  RuntimeError in logs:    {runtime_error_in_logs}")
    log.info("=" * 60)

    # TEST 2 assertions
    if error_2 is None:
        # Success! The weight proof was received despite the slow connection.
        # This means the progress-based timeout is working correctly.
        assert wp_response_2 is not None, "TEST 2: Response object was None but no error"
        assert isinstance(wp_response_2, full_node_protocol.RespondProofOfWeight)
        assert wp_response_2.wp is not None

        # Validate the weight proof
        (
            validated_2,
            val_error_2,
            _fork_point_2,
        ) = await full_node_2.full_node.weight_proof_handler.validate_weight_proof(wp_response_2.wp)
        assert validated_2, f"TEST 2 weight proof validation failed: {val_error_2}"

        log.info(f"TEST 2 PASSED: Weight proof downloaded and validated in {download_time_2:.2f}s")
        log.info("  Progress-based timeout is working correctly!")
    elif runtime_error_in_logs:
        # The websocket timed out and RuntimeError was logged - this is the bug we need to fix
        assert False, (
            f"TEST 2 FAILED: Weight proof download timed out after {download_time_2:.2f}s. "
            f"RuntimeError 'Weight proof did not arrive in time from peer' was logged. "
            f"Websocket improvements are needed to handle slow connections without timing out."
        )
    else:
        # Got None response but no RuntimeError in logs - unexpected failure mode
        assert False, (
            f"TEST 2 FAILED: Weight proof response was None after {download_time_2:.2f}s, "
            f"but RuntimeError 'Weight proof did not arrive in time from peer' was NOT found in logs. "
            f"Error: {error_2}"
        )
