from __future__ import annotations

from dataclasses import dataclass

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.protocols.full_node_protocol import RequestTransaction
from chia.protocols.protocol_message_type_to_node_type import ProtocolMessageTypeToNodeType
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RespondToPhUpdates
from chia.server.api_protocol import ApiMetadata
from chia.util.streamable import Streamable, streamable


def test_api_protocol_raises_for_repeat_request_registration() -> None:
    metadata = ApiMetadata()

    @metadata.request(request_type=ProtocolMessageTypes.handshake)
    async def f(self: object, request: RequestTransaction) -> None: ...

    async def g(self: object, request: RequestTransaction) -> None: ...

    decorator = metadata.request(request_type=ProtocolMessageTypes.handshake)

    with pytest.raises(Exception, match="request type already registered"):
        decorator(g)


def test_protocol_message_type_to_node_type() -> None:
    missing = [msg_type for msg_type in ProtocolMessageTypes if msg_type not in ProtocolMessageTypeToNodeType]
    assert not missing, f"Missing ProtocolMessageTypeToNodeType entries for: {[m.name for m in missing]}"


@streamable
@dataclass(frozen=True)
class _MsgWithList(Streamable):
    items: list[bytes32]


@pytest.mark.anyio
async def test_list_limits_without_peer() -> None:
    captured: list[_MsgWithList] = []

    metadata = ApiMetadata()

    @metadata.request(
        request_type=ProtocolMessageTypes.handshake,
        list_limits=lambda self: {"items": 2},
    )
    async def handler(self: object, request: _MsgWithList) -> None:
        captured.append(request)

    ids = [bytes32(i.to_bytes(32, "big")) for i in range(10)]
    blob = bytes(_MsgWithList(ids))

    await handler(None, blob)
    assert len(captured) == 1
    assert len(captured[0].items) == 2
    assert captured[0].items == ids[:2]


@pytest.mark.anyio
async def test_list_limits_on_rust_type() -> None:
    """Rust types don't accept list_limits in from_bytes. Verify the decorator
    falls back to from_bytes() without list_limits, then applies truncation."""
    captured: list[RespondToPhUpdates] = []

    metadata = ApiMetadata()

    @metadata.request(  # type: ignore[type-var]
        request_type=ProtocolMessageTypes.new_peak,
        list_limits=lambda self: {"puzzle_hashes": 3},
    )
    async def handler(self: object, request: RespondToPhUpdates) -> None:
        captured.append(request)

    phs = [bytes32(i.to_bytes(32, "big")) for i in range(10)]
    blob = bytes(RespondToPhUpdates(phs, uint32(0), []))

    await handler(None, blob)
    assert len(captured) == 1
    # Rust from_bytes is called without list_limits (would TypeError otherwise),
    # followed by _apply_list_limits which calls truncate.
    assert len(captured[0].puzzle_hashes) == 3
    assert captured[0].puzzle_hashes == phs[:3]
