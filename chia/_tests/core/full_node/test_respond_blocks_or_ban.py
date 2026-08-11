from __future__ import annotations

import logging
from typing import cast

import pytest
from chia_rs import FullBlock
from chia_rs.sized_ints import uint16, uint32

from chia._tests.util.network_protocol_data import full_block
from chia.full_node.full_node import respond_blocks_or_ban
from chia.protocols.full_node_protocol import RespondBlocks
from chia.protocols.protocol_timing import CONSENSUS_ERROR_BAN_SECONDS
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo
from chia.util.recursive_replace import recursive_replace


def _block(height: int) -> FullBlock:
    return cast(FullBlock, recursive_replace(full_block, "reward_chain_block.height", uint32(height)))


class DummyPeer:
    def __init__(self) -> None:
        self.closed = False
        self.ban_seconds: int | None = None
        self.peer_info = PeerInfo("127.0.0.1", uint16(8444))

    async def close(self, ban_seconds: int = 0, *args: object, **kwargs: object) -> None:
        self.closed = True
        self.ban_seconds = ban_seconds


@pytest.mark.anyio
async def test_respond_blocks_or_ban_accepts_exact_range() -> None:
    peer = DummyPeer()
    response = RespondBlocks(uint32(5), uint32(7), [_block(5), _block(6), _block(7)])

    assert await respond_blocks_or_ban(cast(WSChiaConnection, peer), response, 5, 7, logging.getLogger(__name__))
    assert not peer.closed
    assert peer.ban_seconds is None


@pytest.mark.parametrize(
    ("start_height", "end_height", "response"),
    [
        (5, 7, RespondBlocks(uint32(5), uint32(7), [])),
        (5, 7, RespondBlocks(uint32(5), uint32(7), [_block(5), _block(6)])),
        (5, 7, RespondBlocks(uint32(5), uint32(7), [_block(7), _block(6), _block(5)])),
        (5, 7, RespondBlocks(uint32(5), uint32(8), [_block(5), _block(6), _block(7)])),
        (5, 7, RespondBlocks(uint32(5), uint32(7), [_block(2), _block(3), _block(4)])),
        (5, 7, RespondBlocks(uint32(5), uint32(7), [_block(8), _block(9), _block(10)])),
        (5, 7, RespondBlocks(uint32(5), uint32(7), [_block(5), _block(12), _block(6)])),
        (5, 7, RespondBlocks(uint32(5), uint32(7), [_block(5), _block(6), _block(6), _block(7)])),
    ],
    ids=[
        "empty",
        "short_prefix",
        "reordered",
        "wrong_end_metadata",
        "entirely_below_range",
        "entirely_above_range",
        "noncontiguous",
        "duplicates",
    ],
)
@pytest.mark.anyio
async def test_respond_blocks_or_ban_rejects_mismatched_payloads(
    start_height: int,
    end_height: int,
    response: RespondBlocks,
) -> None:
    peer = DummyPeer()

    assert not await respond_blocks_or_ban(
        cast(WSChiaConnection, peer), response, start_height, end_height, logging.getLogger(__name__)
    )
    assert peer.closed
    assert peer.ban_seconds == CONSENSUS_ERROR_BAN_SECONDS
