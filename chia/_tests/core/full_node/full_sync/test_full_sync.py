from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, cast

import pytest
from chia_rs import ConsensusConstants, FullBlock, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64, uint128

from chia._tests.conftest import ConsensusMode
from chia._tests.core.node_height import node_height_between, node_height_exactly
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.sync_store import Peak
from chia.protocols import full_node_protocol
from chia.protocols.shared_protocol import Capability
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
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
async def test_short_sync_batch_returns_false_on_disconnected_first_block(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
) -> None:
    # When the first block of a downloaded batch has a parent we do not have in our
    # database, short_sync_batch falls back to long sync by returning False (as its
    # docstring promises) rather than raising.
    _full_node_1, full_node_2, _server_1, _server_2, bt = two_nodes
    node = full_node_2.full_node
    blocks = bt.get_consecutive_blocks(2)
    disconnected_block = blocks[-1]  # height > 0 and its parent is not in node's database

    class _FakePeer:
        peer_node_id = bytes32(b"\x01" * 32)

        def get_peer_logging(self) -> PeerInfo:
            return PeerInfo("127.0.0.1", uint16(0))

        async def call_api(
            self, api_function: Any, request: full_node_protocol.RequestBlocks
        ) -> full_node_protocol.RespondBlocks:
            return full_node_protocol.RespondBlocks(request.start_height, request.end_height, [disconnected_block])

    peer = cast(WSChiaConnection, _FakePeer())
    # start_height == 0 skips the fork-point probe, exercising the batch loop's parent check directly.
    result = await node.short_sync_batch(peer, uint32(0), uint32(1))
    assert result is False
    assert peer.peer_node_id not in node.sync_store.batch_syncing


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
    await time_out_assert(5, lambda: full_node_3.full_node.server.node_id in server_2.all_connections)
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
            s.challenge_merkle_root,  # Keep existing challenge merkle root
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
# todo_v2_plots fix this test and remove limit_consensus_modes
@pytest.mark.limit_consensus_modes(
    allowed=[ConsensusMode.PLAIN, ConsensusMode.HARD_FORK_2_0],
    reason="farming v2 plots is too inefficient still. Enable these tests once it's fast",
)
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


# Tests below cover the inflated-peak-weight regression: detection of peers
# that advertise an inflated peak weight via NewPeak. The defense lives in
# `_sync()`'s peer-confirmation gather loop: if the actual block weight
# returned via RequestBlock differs from the advertised peak weight, every
# peer that advertised that exact peak via NewPeak is banned. Two defining
# properties of the fix:
#
# 1. Banning happens *before* `request_validate_wp()` runs, so the two
#    negative tests below monkeypatch `request_validate_wp` to a sentinel and
#    assert it was never reached. On unpatched code, control still reaches
#    `request_validate_wp` and the eventual ban happens via the weight-proof
#    timeout / mismatch path, so this assertion distinguishes patched from
#    unpatched behavior.
#
# 2. The set of peers to ban is snapshotted at peak-selection time (via
#    `SyncStore.get_advertisers_of_peak`). A peer that overwrites its
#    `peer_to_peak` entry with a fresh `NewPeak` during the peer-confirmation
#    round-trip cannot escape banning. See
#    `test_long_sync_advertiser_overwriting_peer_to_peak_is_still_banned`.


async def _connect_with_quiet_node_2(
    server_1: ChiaServer,
    server_2: ChiaServer,
    full_node_2: FullNodeAPI,
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connect node_2 to node_1 and silence node_2's NewPeak handler so the
    auto-broadcast from node_1 cannot overwrite the peak entries the test
    injects directly into node_2's sync_store."""

    async def noop_new_peak(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(full_node_2.full_node, "new_peak", noop_new_peak)
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)

    async def connected() -> bool:
        return server_1.node_id in full_node_2.full_node.server.all_connections

    await time_out_assert(10, connected)


@pytest.mark.anyio
async def test_long_sync_advertised_weight_lie_bans_advertiser(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_1000_blocks: list[FullBlock],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_node_1, full_node_2, server_1, server_2, _bt = two_nodes

    for block in default_1000_blocks[:200]:
        await full_node_1.full_node.add_block(block)
    real_peak = full_node_1.full_node.blockchain.get_peak()
    assert real_peak is not None

    await _connect_with_quiet_node_2(server_1, server_2, full_node_2, self_hostname, monkeypatch)
    full_node_2.full_node.config["max_sync_wait"] = 0

    # Frame node_1: claim it advertised the real header_hash with a wildly
    # inflated weight via NewPeak. Also stage two stale entries so we can verify
    # the helper bans only peers whose (header_hash, weight) actually match.
    inflated_weight = uint128(real_peak.weight + 10**12)
    full_node_2.full_node.sync_store.peer_has_block(
        real_peak.header_hash, server_1.node_id, inflated_weight, real_peak.height, True
    )
    disconnected_liar = bytes32(b"\x11" * 32)
    full_node_2.full_node.sync_store.peer_has_block(
        real_peak.header_hash, disconnected_liar, inflated_weight, real_peak.height, True
    )
    bystander = bytes32(b"\x22" * 32)
    full_node_2.full_node.sync_store.peer_has_block(
        real_peak.header_hash, bystander, real_peak.weight, real_peak.height, True
    )

    # Fail loudly if control ever reaches the weight-proof request. On unpatched
    # code, the ban happens via that path (after the WP response/timeout); the
    # fix's defining property is that we bail at peer-confirmation instead.
    reached_wp_validation = False

    async def fail_if_wp_called(*_args: object, **_kwargs: object) -> None:
        nonlocal reached_wp_validation  # pragma: no cover  (sentinel; only fires on unpatched code)
        reached_wp_validation = True  # pragma: no cover
        raise AssertionError(  # pragma: no cover
            "request_validate_wp must not be reached when a weight lie is detected"
        )

    monkeypatch.setattr(full_node_2.full_node, "request_validate_wp", fail_if_wp_called)

    await full_node_2.full_node._sync()

    # node_1 confirmed the block with its real (smaller) weight, exposing the
    # injected lie. node_1 must be banned; the bystander entry advertising the
    # honest weight must remain untouched.
    async def liar_disconnected() -> bool:
        return server_1.node_id not in full_node_2.full_node.server.all_connections

    await time_out_assert(10, liar_disconnected)
    assert not reached_wp_validation
    assert full_node_2.full_node.blockchain.get_peak() is None
    assert bystander in full_node_2.full_node.sync_store.peer_to_peak
    assert full_node_2.full_node.sync_store.peer_to_peak[bystander].weight == real_peak.weight


@pytest.mark.anyio
async def test_long_sync_no_peer_confirms_peak_bans_advertiser(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_1000_blocks: list[FullBlock],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_node_1, full_node_2, server_1, server_2, _bt = two_nodes

    for block in default_1000_blocks[:200]:
        await full_node_1.full_node.add_block(block)

    await _connect_with_quiet_node_2(server_1, server_2, full_node_2, self_hostname, monkeypatch)
    full_node_2.full_node.config["max_sync_wait"] = 0

    # node_1 claims a peak that does not exist on the network, so no peer can
    # return a matching block via RequestBlock.
    fabricated_hash = std_hash(b"inflated-peak-no-confirm")
    fabricated_height = uint32(50_000)
    fabricated_weight = uint128(10**15)
    full_node_2.full_node.sync_store.peer_has_block(
        fabricated_hash, server_1.node_id, fabricated_weight, fabricated_height, True
    )

    # Fail loudly if control ever reaches the weight-proof request. On
    # unpatched code, the ban happens via that path (after the WP timeout);
    # the fix bails at peer-confirmation when no peer can serve the block.
    reached_wp_validation = False

    async def fail_if_wp_called(*_args: object, **_kwargs: object) -> None:
        nonlocal reached_wp_validation  # pragma: no cover  (sentinel; only fires on unpatched code)
        reached_wp_validation = True  # pragma: no cover
        raise AssertionError(  # pragma: no cover
            "request_validate_wp must not be reached when no peer confirms the peak"
        )

    monkeypatch.setattr(full_node_2.full_node, "request_validate_wp", fail_if_wp_called)

    await full_node_2.full_node._sync()

    async def liar_disconnected() -> bool:
        return server_1.node_id not in full_node_2.full_node.server.all_connections

    await time_out_assert(10, liar_disconnected)
    assert not reached_wp_validation
    assert full_node_2.full_node.blockchain.get_peak() is None


@pytest.mark.anyio
async def test_long_sync_honest_advertiser_not_banned(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_1000_blocks: list[FullBlock],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_node_1, full_node_2, server_1, server_2, _bt = two_nodes

    for block in default_1000_blocks[:200]:
        await full_node_1.full_node.add_block(block)
    real_peak = full_node_1.full_node.blockchain.get_peak()
    assert real_peak is not None

    await _connect_with_quiet_node_2(server_1, server_2, full_node_2, self_hostname, monkeypatch)
    full_node_2.full_node.config["max_sync_wait"] = 0

    # Stop _sync once it reaches weight-proof validation; everything beyond
    # that point (WP fetch + chain download) is out of scope for this test.
    # Reaching it proves peer-confirmation passed without raising.
    reached_wp_validation = False

    async def stop_after_peer_confirmation(*_args: object, **_kwargs: object) -> None:
        nonlocal reached_wp_validation
        reached_wp_validation = True
        raise RuntimeError("test: stop after peer confirmation")

    monkeypatch.setattr(full_node_2.full_node, "request_validate_wp", stop_after_peer_confirmation)

    full_node_2.full_node.sync_store.peer_has_block(
        real_peak.header_hash, server_1.node_id, real_peak.weight, real_peak.height, True
    )

    await full_node_2.full_node._sync()

    assert reached_wp_validation
    assert server_1.node_id in full_node_2.full_node.server.all_connections


@pytest.mark.anyio
async def test_ban_uses_snapshot_after_peer_to_peak_mutation(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_ban_peak_weight_liars` uses the snapshot it was given at
    peak-selection time, not the current `peer_to_peak` state. A peer that
    overwrites its `peer_to_peak` entry with a fresh `NewPeak` between
    `_sync()` picking the target peak and the ban firing is still banned.

    On the previous `(header_hash, weight)` lookup the mutated entry would no
    longer match and the attacker would escape the ban; on the snapshot fix
    the attacker is locked in at peak-selection time.
    """
    _full_node_1, full_node_2, server_1, server_2, _bt = two_nodes

    await _connect_with_quiet_node_2(server_1, server_2, full_node_2, self_hostname, monkeypatch)
    sync_store = full_node_2.full_node.sync_store

    real_header_hash = std_hash(b"real-peak")
    inflated_weight = uint128(10**18)
    height = uint32(200)
    sync_store.peer_has_block(real_header_hash, server_1.node_id, inflated_weight, height, True)

    # Production code path: snapshot the advertisers exactly as `_sync()` does,
    # synchronously, right after picking the target peak.
    target_peak = Peak(real_header_hash, height, inflated_weight)
    weight_liars = sync_store.get_advertisers_of_peak(target_peak)
    assert weight_liars == {server_1.node_id}

    # Simulate the attacker sending a fresh `NewPeak` after the snapshot is
    # captured (e.g. during the `asyncio.gather` await in `_sync()`).
    sync_store.peer_has_block(
        std_hash(b"attacker-fresh-peak"),
        server_1.node_id,
        uint128(1),
        uint32(0),
        True,
    )
    # The lookup that `_sync()` used to perform at ban time would no longer
    # find the attacker; the snapshot still does. This is the property the fix
    # relies on.
    assert sync_store.get_advertisers_of_peak(target_peak) == set()
    assert server_1.node_id in weight_liars

    await full_node_2.full_node._ban_peak_weight_liars(weight_liars)

    async def liar_disconnected() -> bool:
        return server_1.node_id not in full_node_2.full_node.server.all_connections

    await time_out_assert(10, liar_disconnected)
