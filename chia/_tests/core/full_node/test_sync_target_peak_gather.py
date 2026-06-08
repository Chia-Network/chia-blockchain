from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint128

from chia._tests.conftest import ConsensusMode
from chia.full_node.full_node import FullNode
from chia.full_node.sync_store import SyncStore
from chia.protocols.full_node_protocol import RespondBlock
from chia.protocols.protocol_timing import CONSENSUS_ERROR_BAN_SECONDS
from chia.types.peer_info import PeerInfo
from chia.util.hash import std_hash


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
async def test_sync_target_peak_gather_skips_deserialize_failure(
    monkeypatch: pytest.MonkeyPatch,
    default_1000_blocks: list[FullBlock],
) -> None:
    """If one peer raises during RequestBlock handling, others still update peer_has_block."""
    block = default_1000_blocks[-1]
    header_hash = block.header_hash
    height = block.height
    weight = block.weight

    sync_store = SyncStore()
    peer_wait = [bytes32(std_hash(i.to_bytes(2, "big"))) for i in range(3)]
    for pid in peer_wait:
        sync_store.peer_has_block(header_hash, pid, weight, height, new_peak=True)

    bad_peer = MagicMock()
    bad_peer.peer_node_id = bytes32(std_hash(b"bad-peer"))
    bad_peer.get_peer_logging = MagicMock(return_value=PeerInfo("10.0.0.1", 8444))
    bad_peer.call_api = AsyncMock(side_effect=ValueError("malformed respond_block body"))
    bad_peer.close = AsyncMock()

    good_peer = MagicMock()
    good_peer.peer_node_id = bytes32(std_hash(b"good-peer"))
    good_peer.get_peer_logging = MagicMock(return_value=PeerInfo("10.0.0.2", 8444))
    good_peer.call_api = AsyncMock(
        return_value=RespondBlock(block),
    )
    good_peer.close = AsyncMock()

    assert good_peer.peer_node_id not in sync_store.peak_to_peer.get(header_hash, set())

    server = MagicMock()
    server.get_connections = MagicMock(return_value=[bad_peer, good_peer])

    node = FullNode.__new__(FullNode)
    node.sync_store = sync_store
    node.log = MagicMock()
    node._shut_down = False
    node.config = {"max_sync_wait": 1}
    monkeypatch.setattr(node, "_state_changed", MagicMock())
    node._server = server

    blockchain = MagicMock()

    @asynccontextmanager
    async def acquire_mutex(**kwargs: object) -> AsyncIterator[None]:
        yield None

    blockchain.priority_mutex.acquire = acquire_mutex
    blockchain.warmup = AsyncMock()
    blockchain.get_peak = MagicMock(return_value=None)
    blockchain.get_full_peak = AsyncMock(return_value=None)
    node._blockchain = blockchain

    async def fake_request_validate_wp(
        self: FullNode,
        peak_header_hash: bytes32,
        peak_height: uint32,
        peak_weight: uint128,
    ) -> tuple[uint32, list[Any]]:
        return uint32(0), []

    async def fake_finish_sync(self: FullNode, fork_point: uint32 | None) -> None:
        sync_store.set_long_sync(False)

    async def fake_sync_from_fork_point(
        self: FullNode,
        fork_point: uint32,
        peak_height: uint32,
        peak_hash: bytes32,
        summaries: list[Any],
    ) -> None:
        return None

    monkeypatch.setattr(FullNode, "request_validate_wp", fake_request_validate_wp)
    monkeypatch.setattr(FullNode, "_finish_sync", fake_finish_sync)
    monkeypatch.setattr(FullNode, "sync_from_fork_point", fake_sync_from_fork_point)
    monkeypatch.setattr(
        "chia.full_node.full_node.check_fork_next_block",
        AsyncMock(return_value=uint32(0)),
    )

    monkeypatch.setattr(node, "get_peers_with_peak", MagicMock(return_value=[]))

    await FullNode._sync(node)

    bad_peer.close.assert_awaited_once_with(CONSENSUS_ERROR_BAN_SECONDS)
    assert good_peer.peer_node_id in sync_store.peak_to_peer[header_hash]
    node.log.warning.assert_called()


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
async def test_sync_target_peak_gather_does_not_ban_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
    default_1000_blocks: list[FullBlock],
) -> None:
    """A peer that times out should be skipped, not banned."""
    block = default_1000_blocks[-1]
    header_hash = block.header_hash
    height = block.height
    weight = block.weight

    sync_store = SyncStore()
    peer_wait = [bytes32(std_hash(i.to_bytes(2, "big"))) for i in range(3)]
    for pid in peer_wait:
        sync_store.peer_has_block(header_hash, pid, weight, height, new_peak=True)

    slow_peer = MagicMock()
    slow_peer.peer_node_id = bytes32(std_hash(b"slow-peer"))
    slow_peer.get_peer_logging = MagicMock(return_value=PeerInfo("10.0.0.3", 8444))
    slow_peer.call_api = AsyncMock(side_effect=TimeoutError("call_api timed out"))
    slow_peer.close = AsyncMock()

    good_peer = MagicMock()
    good_peer.peer_node_id = bytes32(std_hash(b"good-peer-2"))
    good_peer.get_peer_logging = MagicMock(return_value=PeerInfo("10.0.0.2", 8444))
    good_peer.call_api = AsyncMock(return_value=RespondBlock(block))
    good_peer.close = AsyncMock()

    assert good_peer.peer_node_id not in sync_store.peak_to_peer.get(header_hash, set())

    server = MagicMock()
    server.get_connections = MagicMock(return_value=[slow_peer, good_peer])

    node = FullNode.__new__(FullNode)
    node.sync_store = sync_store
    node.log = MagicMock()
    node._shut_down = False
    node.config = {"max_sync_wait": 1}
    monkeypatch.setattr(node, "_state_changed", MagicMock())
    node._server = server

    blockchain = MagicMock()

    @asynccontextmanager
    async def acquire_mutex(**kwargs: object) -> AsyncIterator[None]:
        yield None

    blockchain.priority_mutex.acquire = acquire_mutex
    blockchain.warmup = AsyncMock()
    blockchain.get_peak = MagicMock(return_value=None)
    blockchain.get_full_peak = AsyncMock(return_value=None)
    node._blockchain = blockchain

    async def fake_request_validate_wp(
        self: FullNode,
        peak_header_hash: bytes32,
        peak_height: uint32,
        peak_weight: uint128,
    ) -> tuple[uint32, list[Any]]:
        return uint32(0), []

    async def fake_finish_sync(self: FullNode, fork_point: uint32 | None) -> None:
        sync_store.set_long_sync(False)

    async def fake_sync_from_fork_point(
        self: FullNode,
        fork_point: uint32,
        peak_height: uint32,
        peak_hash: bytes32,
        summaries: list[Any],
    ) -> None:
        return None

    monkeypatch.setattr(FullNode, "request_validate_wp", fake_request_validate_wp)
    monkeypatch.setattr(FullNode, "_finish_sync", fake_finish_sync)
    monkeypatch.setattr(FullNode, "sync_from_fork_point", fake_sync_from_fork_point)
    monkeypatch.setattr(
        "chia.full_node.full_node.check_fork_next_block",
        AsyncMock(return_value=uint32(0)),
    )

    monkeypatch.setattr(node, "get_peers_with_peak", MagicMock(return_value=[]))

    await FullNode._sync(node)

    slow_peer.close.assert_not_awaited()
    assert good_peer.peer_node_id in sync_store.peak_to_peer[header_hash]
