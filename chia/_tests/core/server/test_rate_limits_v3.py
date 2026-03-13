from __future__ import annotations

import asyncio

import pytest
from chia_rs.sized_ints import uint8, uint16, uint32

from chia._tests.conftest import ConsensusMode
from chia._tests.connection_utils import add_dummy_connection_wsc
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import (
    RejectBlocks,
    RequestBlocks,
    RespondBlocks,
)
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability, default_capabilities
from chia.server.rate_limits_v3 import (
    MAX_RL_V3_CONFIG_STRING_BYTES,
    RLSettingsV3,
    rate_limits_v3,
    rl_settings_v3_from_capabilities,
    rl_v3_to_capability_string,
)
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.peer_info import PeerInfo
from chia.util.task_referencer import create_referenced_task


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_oversized_config_string(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    _, server, _ = one_node_one_block
    oversized_config_string = "0" * (MAX_RL_V3_CONFIG_STRING_BYTES + 1)
    with pytest.raises(Exception, match="Error code: INVALID_HANDSHAKE"):
        await add_dummy_connection_wsc(
            server,
            self_hostname,
            42,
            additional_capabilities=[(uint16(Capability.RATE_LIMITS_V3.value), oversized_config_string)],
        )


def test_rl_v3_roundtrip() -> None:
    """
    Covers the scenario where we encode our local `rate_limits_v3` global
    defaults into a capability string then parse it back to make sure we get
    the same settings back.
    """
    capabilities = [(uint16(Capability.RATE_LIMITS_V3.value), rl_v3_to_capability_string())]
    parsed_rate_limits_v3 = rl_settings_v3_from_capabilities(capabilities)
    assert parsed_rate_limits_v3 == rate_limits_v3


def test_rl_settings_v3_from_capabilities() -> None:
    """
    Covers `rl_settings_v3_from_capabilities` to make sure that any non zero
    value is interpreted as a potential list, and that we fall back to the
    global defaults on any issues instead of disabling the v3 capability.
    """

    def capabilities_from_rl_string(rl_v3_string: str) -> list[tuple[uint16, str]]:
        return [(uint16(Capability.RATE_LIMITS_V3.value), rl_v3_string)]

    # "0" disables the v3 capability and anything else enables it
    assert rl_settings_v3_from_capabilities(capabilities_from_rl_string("0")) == {}
    assert rl_settings_v3_from_capabilities(capabilities_from_rl_string("1")) == rate_limits_v3
    assert rl_settings_v3_from_capabilities(capabilities_from_rl_string("")) == rate_limits_v3
    # Partial list
    encoded = f"{ProtocolMessageTypes.request_blocks.value}:5:200"
    parsed = rl_settings_v3_from_capabilities(capabilities_from_rl_string(encoded))
    assert parsed[ProtocolMessageTypes.request_blocks].window_size == 5
    assert parsed[ProtocolMessageTypes.request_blocks].max_message_size == 200
    # Make sure this was not altered by the partial override
    assert parsed[ProtocolMessageTypes.request_block] == rate_limits_v3[ProtocolMessageTypes.request_block]
    # Partially malformed string
    encoded = "29:4:110,foo,60:5:1048576"
    parsed = rl_settings_v3_from_capabilities(capabilities_from_rl_string(encoded))
    expected = dict(rate_limits_v3)
    # This is request_blocks
    expected[ProtocolMessageTypes(29)] = RLSettingsV3(window_size=4, max_message_size=110)
    # This is request_header_blocks
    expected[ProtocolMessageTypes(60)] = RLSettingsV3(window_size=5, max_message_size=1048576)
    assert parsed == expected
    # Completely malformed string so we return the default limits
    assert rl_settings_v3_from_capabilities(capabilities_from_rl_string("xyz")) == rate_limits_v3
    # Zero or negative windows size
    encoded = f"{ProtocolMessageTypes.request_blocks.value}:0:100,{ProtocolMessageTypes.request_block.value}:-1:100"
    parsed = rl_settings_v3_from_capabilities(capabilities_from_rl_string(encoded))
    assert parsed[ProtocolMessageTypes.request_blocks] == rate_limits_v3[ProtocolMessageTypes.request_blocks]
    assert parsed[ProtocolMessageTypes.request_block] == rate_limits_v3[ProtocolMessageTypes.request_block]
    # Zero or negative max message size
    encoded = f"{ProtocolMessageTypes.request_blocks.value}:3:0,{ProtocolMessageTypes.request_block.value}:3:-1"
    parsed = rl_settings_v3_from_capabilities(capabilities_from_rl_string(encoded))
    assert parsed[ProtocolMessageTypes.request_blocks] == rate_limits_v3[ProtocolMessageTypes.request_blocks]
    assert parsed[ProtocolMessageTypes.request_block] == rate_limits_v3[ProtocolMessageTypes.request_block]
    # Invalid message type
    encoded = "2:3:4"
    parsed = rl_settings_v3_from_capabilities(capabilities_from_rl_string(encoded))
    assert parsed == rate_limits_v3


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("rl_v3_enabled", [False, True])
async def test_v3_message_types_initialization(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools], self_hostname: str, rl_v3_enabled: bool
) -> None:
    """
    Covers the scenario where we connect to a peer that advertises the
    RATE_LIMITS_V3 capability and we initialize the in-flight windows for all
    supported protocol message types as well as the peer's settings from the
    RATE_LIMITS_V3 capability string.
    """
    _, server, _ = one_node_one_block
    additional_capabilities = (
        [(uint16(Capability.RATE_LIMITS_V3.value), rl_v3_to_capability_string())] if rl_v3_enabled else []
    )
    _, peer_id = await add_dummy_connection_wsc(
        server, self_hostname, 1337, additional_capabilities=additional_capabilities
    )
    await time_out_assert(5, lambda: peer_id in server.all_connections)
    receiver_connection = server.all_connections[peer_id]
    for msg_type in rate_limits_v3:
        if rl_v3_enabled:
            assert msg_type in receiver_connection.peer_rl_settings_v3
        rl_window = receiver_connection.rate_limit_windows.get(msg_type)
        assert rl_window is not None
        assert rl_window.receive_window == 0
        assert rl_window.congestion_window == 0


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_inbound_oversized_message(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools], self_hostname: str
) -> None:
    """
    Covers the scenario where we enforce peer's max message size limit on a
    protocol message type.
    """
    _, server, _ = one_node_one_block
    sender_connection, peer_id = await add_dummy_connection_wsc(server, self_hostname, 42)
    await time_out_assert(5, lambda: peer_id in server.all_connections)
    server.all_connections[peer_id].peer_info = PeerInfo("1.3.3.7", 42)
    msg_type = ProtocolMessageTypes.request_blocks
    oversized_msg = Message(uint8(msg_type.value), uint16(1337), bytes(rate_limits_v3[msg_type].max_message_size + 1))
    await sender_connection.send_message(oversized_msg)
    await time_out_assert(5, lambda: sender_connection.closed)
    await time_out_assert(5, lambda: "1.3.3.7" in server.banned_peers)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_receive_window(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers in-flight receive windows in general and specifically the
    scenario where we enforce it for multiple peers on multiple protocol
    message types at the same time.
    """
    _, server, _ = one_node_one_block
    sender_connection1, sender_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
    await time_out_assert(5, lambda: sender_id in server.all_connections)
    receiver_connection1 = server.all_connections[sender_id]
    receiver_connection1.peer_info = PeerInfo("1.3.3.7", receiver_connection1.peer_info.port)
    sender_connection2, sender2_id = await add_dummy_connection_wsc(server, self_hostname, 1234)
    await time_out_assert(5, lambda: sender2_id in server.all_connections)
    receiver_connection2 = server.all_connections[sender2_id]
    receiver_connection2.peer_info = PeerInfo("1.2.3.4", receiver_connection2.peer_info.port)
    localhost_sender, localhost_peer_id = await add_dummy_connection_wsc(server, self_hostname, 5678)
    await time_out_assert(5, lambda: localhost_peer_id in server.all_connections)
    msg_type = ProtocolMessageTypes.request_blocks
    release_handler = asyncio.Event()

    async def slow_handler(api: FullNodeAPI, request_bytes: bytes) -> Message | None:
        await release_handler.wait()
        return None

    request_blocks_api = receiver_connection1.api.metadata.message_type_to_request[msg_type]
    monkeypatch.setattr(request_blocks_api, "method", slow_handler)
    max_concurrent = rate_limits_v3[msg_type].window_size

    async def peer1_task() -> None:
        # Peer 1 sends more than max_concurrent rapid-fire
        msg = make_msg(msg_type, RequestBlocks(uint32(0), uint32(0), True))
        for _ in range(max_concurrent + 1):
            await sender_connection1.send_message(msg)

    async def peer2_task() -> None:
        for _ in range(max_concurrent):
            await sender_connection2.send_message(make_msg(msg_type, RequestBlocks(uint32(0), uint32(0), False)))

    async def localhost_task() -> None:
        # localhost peer is exempt from rate limits v3
        for _ in range(max_concurrent + 42):
            await localhost_sender.send_message(make_msg(msg_type, RequestBlocks(uint32(0), uint32(0), False)))

    await asyncio.gather(peer1_task(), peer2_task(), localhost_task())
    # Peer1 hits the limit
    await time_out_assert(5, lambda: sender_connection1.closed)
    await time_out_assert(5, lambda: "1.3.3.7" in server.banned_peers)
    # The others are fine
    assert sender_connection2.closed is False
    assert localhost_sender.closed is False
    release_handler.set()
    await time_out_assert(5, lambda: receiver_connection2.rate_limit_windows[msg_type].receive_window == 0)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_receive_window_pre_queue_check(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where the (unreliable) receive window check in
    `_read_one_message` kicks in and rejects a message before it gets enqueued
    for processing. We fill the window by letting handlers start and then
    before they complete we send one more message and make sure it gets
    rejected before entering the queue.
    """
    _, server, _ = one_node_one_block
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
    await time_out_assert(5, lambda: sender_id in server.all_connections)
    receiver_connection = server.all_connections[sender_id]
    receiver_connection.peer_info = PeerInfo("1.3.3.7", receiver_connection.peer_info.port)
    msg_type = ProtocolMessageTypes.request_blocks
    release_handler = asyncio.Event()

    async def slow_handler(api: FullNodeAPI, request_bytes: bytes) -> Message | None:
        await release_handler.wait()
        return None  # pragma: no cover

    request_blocks_api = receiver_connection.api.metadata.message_type_to_request[msg_type]
    monkeypatch.setattr(request_blocks_api, "method", slow_handler)
    max_concurrent = rate_limits_v3[msg_type].window_size
    rl_window = receiver_connection.rate_limit_windows[msg_type]
    # Send exactly max_concurrent messages and wait for handlers to start
    msg = make_msg(msg_type, RequestBlocks(uint32(0), uint32(0), False))
    for _ in range(max_concurrent):
        await sender_connection.send_message(msg)
    await time_out_assert(5, lambda: rl_window.receive_window == max_concurrent)
    # This message should be rejected in _read_one_message
    await sender_connection.send_message(msg)
    await time_out_assert(5, lambda: sender_connection.closed)
    await time_out_assert(5, lambda: "1.3.3.7" in server.banned_peers)
    release_handler.set()
    await time_out_assert(5, lambda: rl_window.receive_window == 0)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("server_custom_config", [False, True])
@pytest.mark.parametrize("bigger_window_size", [False, True])
async def test_congestion_window(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
    server_custom_config: bool,
    bigger_window_size: bool,
) -> None:
    """
    Covers the scenario where the peer hits the congestion window for a
    protocol request type, and further requests of that type get dropped and
    retried.
    With `server_custom_config` we control whether we advertise a custom config
    string with different window size and we make sure the peer honours that
    value instead of the global default one.
    With `bigger_window_size` we control whether the custom config advertises a
    bigger or smaller window size than the default.
    """
    _, server, _ = one_node_one_block
    msg_type = ProtocolMessageTypes.request_blocks
    test_window_size = rate_limits_v3[msg_type].window_size
    if server_custom_config:
        # Configure a different window size
        test_window_size += 1 if bigger_window_size else -1
        # Update the server's global defaults and advertised v3 capability
        monkeypatch.setitem(
            rate_limits_v3,
            msg_type,
            RLSettingsV3(window_size=test_window_size, max_message_size=rate_limits_v3[msg_type].max_message_size),
        )
        capability_str = f"{msg_type.value}:{test_window_size}:{rate_limits_v3[msg_type].max_message_size}"
        capabilities = default_capabilities[NodeType.FULL_NODE] + [
            (uint16(Capability.RATE_LIMITS_V3.value), capability_str)
        ]
        server.set_capabilities(capabilities)
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
    await time_out_assert(5, lambda: sender_id in server.all_connections)
    receiver_connection = server.all_connections[sender_id]
    receiver_connection.peer_info = PeerInfo("1.3.3.7", receiver_connection.peer_info.port)
    sender_connection.peer_info = PeerInfo("1.2.3.4", sender_connection.peer_info.port)
    # Make sure the peer's settings are properly set from the capability string
    assert sender_connection.peer_rl_settings_v3[msg_type].window_size == test_window_size
    max_concurrent = test_window_size
    original_method = receiver_connection.api.metadata.message_type_to_request[msg_type].method
    handler_called_event = asyncio.Event()
    release_event = asyncio.Event()

    async def slow_handler(api: FullNodeAPI, request_bytes: bytes) -> Message | None:
        handler_called_event.set()
        # Wait until get the signal to proceed
        await release_event.wait()
        # delegate to the real implementation so that we return a valid response
        return await original_method(api, request_bytes)

    # Delay the handler's responses so we can fill the slots
    monkeypatch.setattr(receiver_connection.api.metadata.message_type_to_request[msg_type], "method", slow_handler)
    # Fill the congestion window
    for _ in range(max_concurrent):
        handler_called_event.clear()
        create_referenced_task(
            sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
        )
        await time_out_assert(5, handler_called_event.is_set)

    rl_window = sender_connection.rate_limit_windows[msg_type]
    assert rl_window.congestion_window == max_concurrent
    # This extra request should now be dropped and retried
    request_task = create_referenced_task(
        sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
    )
    # Unblock the original handlers so the congestion window can drain
    release_event.set()
    # The retried request should eventually complete with a real response
    result = await asyncio.wait_for(request_task, timeout=5)
    assert isinstance(result, RespondBlocks)
    assert result.start_height == uint32(0)
    assert result.end_height == uint32(0)
    assert len(result.blocks) == 1
    await time_out_assert(5, lambda: rl_window.congestion_window == 0)
    # A fresh request should succeed
    result = await sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
    assert isinstance(result, RespondBlocks)
    assert rl_window.congestion_window == 0


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_congestion_window_send_request_timeout(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where `send_request` times out waiting for a response
    to make sure the congestion window is properly updated.
    """
    _, server, _ = one_node_one_block
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
    receiver_connection = server.all_connections[sender_id]
    receiver_connection.peer_info = PeerInfo("1.3.3.7", receiver_connection.peer_info.port)
    msg_type = ProtocolMessageTypes.request_blocks

    async def hanging_handler(api: FullNodeAPI, request_bytes: bytes) -> None:
        await asyncio.sleep(42)

    request_meta = receiver_connection.api.metadata.message_type_to_request[msg_type]
    monkeypatch.setattr(request_meta, "method", hanging_handler)
    msg = make_msg(msg_type, RequestBlocks(uint32(0), uint32(0), False))
    result = await sender_connection.send_request(msg, timeout=1)
    assert result is None
    # Make sure the congestion window is properly updated
    assert sender_connection.rate_limit_windows[msg_type].congestion_window == 0


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("server_custom_config", [False, True])
@pytest.mark.parametrize("bigger_max_msg_size", [False, True])
async def test_outbound_oversized_message(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
    server_custom_config: bool,
    bigger_max_msg_size: bool,
) -> None:
    """
    Covers the scenario where we send a message with larger size than the max to
    make sure it doesn't get sent.
    With `server_custom_config` we control whether we advertise a custom config
    string with different max message size and we make sure the peer honours
    that value instead of the global default one.
    With `bigger_max_msg_size` we control whether the custom config advertises a
    bigger or smaller max message size than the default.
    """
    _, server, _ = one_node_one_block
    msg_type = ProtocolMessageTypes.request_blocks
    test_max_message_size = rate_limits_v3[msg_type].max_message_size
    if server_custom_config:
        # pick a value either below or above the default
        test_max_message_size += 42 if bigger_max_msg_size else -42
        # update server global defaults so it doesn't treat us as misbehaving
        monkeypatch.setitem(
            rate_limits_v3,
            msg_type,
            RLSettingsV3(window_size=rate_limits_v3[msg_type].window_size, max_message_size=test_max_message_size),
        )
        cap_str = f"{msg_type.value}:{rate_limits_v3[msg_type].window_size}:{test_max_message_size}"
        capabilities = default_capabilities[NodeType.FULL_NODE] + [
            (uint16(Capability.RATE_LIMITS_V3.value), cap_str),
        ]
        server.set_capabilities(capabilities)
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 42)
    await time_out_assert(5, lambda: sender_id in server.all_connections)
    sender_connection.peer_info = PeerInfo("1.3.3.7", sender_connection.peer_info.port)
    # Make sure the peer's settings are properly set from the capability string
    assert sender_connection.peer_rl_settings_v3[msg_type].max_message_size == test_max_message_size
    event = asyncio.Event()

    async def test_send_bytes(data: bytes, compress: int | None = None) -> None:
        # We won't reach this because the rate limiter will block the
        # oversized message.
        event.set()  # pragma: no cover

    monkeypatch.setattr(sender_connection.ws, "send_bytes", test_send_bytes)
    oversized_msg = make_msg(msg_type, bytes(test_max_message_size + 1))
    await sender_connection.send_message(oversized_msg)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=1)
    assert sender_connection.closed is False


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_close_unblocks_send_request(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where we close a connection while `send_request` is
    blocked to ensure it returns `None` and decrements the congestion window.
    """
    _, server, _ = one_node_one_block
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
    await time_out_assert(5, lambda: sender_id in server.all_connections)
    receiver_connection = server.all_connections[sender_id]
    receiver_connection.peer_info = PeerInfo("1.3.3.7", receiver_connection.peer_info.port)
    sender_connection.peer_info = PeerInfo("1.2.3.4", sender_connection.peer_info.port)
    msg_type = ProtocolMessageTypes.request_blocks
    max_concurrent = rate_limits_v3[msg_type].window_size
    # Create a slow handler so that the initial requests fill the window and
    # one additional request gets stalled in `_send_message` retry logic.
    handler_called = asyncio.Event()
    release = asyncio.Event()
    original_method = receiver_connection.api.metadata.message_type_to_request[msg_type].method

    async def slow_handler(api: FullNodeAPI, request_bytes: bytes) -> Message | None:
        handler_called.set()
        await release.wait()
        return await original_method(api, request_bytes)

    monkeypatch.setattr(receiver_connection.api.metadata.message_type_to_request[msg_type], "method", slow_handler)
    # Fill the congestion window
    for _ in range(max_concurrent):
        handler_called.clear()
        create_referenced_task(
            sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
        )
        await time_out_assert(5, handler_called.is_set)
    rl_window = sender_connection.rate_limit_windows[msg_type]
    assert rl_window.congestion_window == max_concurrent
    # Issue one more request, it will be dropped and retried internally
    blocked_task = create_referenced_task(
        sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
    )
    await asyncio.sleep(0.1)
    # Now close the connection and check that `send_request` returns `None`
    await sender_connection.close()
    result = await asyncio.wait_for(blocked_task, timeout=5)
    assert result is None
    # The congestion window should update properly
    release.set()
    await time_out_assert(5, lambda: rl_window.congestion_window == 0)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_api_handler_raises_exception(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where an API handler raises an exception, to make sure
    we decrement the receive window.
    """
    _, server, _ = one_node_one_block
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
    await time_out_assert(5, lambda: sender_id in server.all_connections)
    receiver_connection = server.all_connections[sender_id]
    receiver_connection.peer_info = PeerInfo("1.3.3.7", receiver_connection.peer_info.port)
    msg_type = ProtocolMessageTypes.request_blocks
    rl_window = receiver_connection.rate_limit_windows[msg_type]

    async def throwing_api_handler(api: FullNodeAPI, request_bytes: bytes) -> None:
        assert rl_window.receive_window == 1
        raise Exception

    request_meta = receiver_connection.api.metadata.message_type_to_request[msg_type]
    monkeypatch.setattr(request_meta, "method", throwing_api_handler)
    result = await sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
    assert result is None
    await time_out_assert(5, lambda: rl_window.receive_window == 0)
    await time_out_assert(5, lambda: receiver_connection.closed)
    await time_out_assert(5, lambda: "1.3.3.7" in server.banned_peers)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_v3_messages_bypass_v2_rate_limiter(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where we send a v3 supported protocol message to a
    peer that advertises RATE_LIMITS_V3 to make sure the v2 rate limiter gets
    properly bypassed.
    """
    _, server, _ = one_node_one_block
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 42)
    await time_out_assert(5, lambda: sender_id in server.all_connections)
    sender_connection.peer_info = PeerInfo("1.3.3.7", sender_connection.peer_info.port)
    msg_type = ProtocolMessageTypes.request_blocks
    event = asyncio.Event()

    def test_process_msg_and_check(
        message: Message, our_capabilities: list[Capability], peer_capabilities: list[Capability]
    ) -> str | None:  # pragma: no cover
        event.set()
        return None

    monkeypatch.setattr(sender_connection.outbound_rate_limiter, "process_msg_and_check", test_process_msg_and_check)
    # V2 rate limiter should not be invoked for v3 supported types
    await sender_connection.send_message(make_msg(msg_type, RequestBlocks(uint32(0), uint32(0), False)))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=1)
    # Make sure the connection remains open
    assert sender_connection.closed is False


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_rate_limits_v3_e2e(
    two_nodes_one_block: tuple[FullNodeSimulator, FullNodeSimulator, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
) -> None:
    """
    Covers rate limits v3 end to end. It verifies RATE_LIMITS_V3 capability
    as well as the receive and congestion windows.
    """
    full_node_api, _, server_1, server_2, _ = two_nodes_one_block
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()))
    await time_out_assert(5, lambda: len(server_1.all_connections) == 1)
    await time_out_assert(5, lambda: len(server_2.all_connections) == 1)
    sender_connection = next(iter(server_2.all_connections.values()))
    sender_connection.peer_info = PeerInfo("1.3.3.7", server_1.get_port())
    receiver_connection = next(iter(server_1.all_connections.values()))
    receiver_connection.peer_info = PeerInfo("1.2.3.4", server_2.get_port())
    # Capability advertising
    assert Capability.RATE_LIMITS_V3 in sender_connection.peer_capabilities
    assert Capability.RATE_LIMITS_V3 in receiver_connection.peer_capabilities
    # Rate limits v3 windows should have initialized correctly on both sides
    msg_type = ProtocolMessageTypes.request_blocks
    sender_rl_window = sender_connection.rate_limit_windows[msg_type]
    receiver_rl_window = receiver_connection.rate_limit_windows[msg_type]
    assert sender_rl_window.receive_window == 0
    assert receiver_rl_window.receive_window == 0
    # Issue a request to verify the windows state after its completion
    test_block = (await full_node_api.full_node.block_store.get_full_blocks_at([uint32(0)]))[0]
    result = await sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
    assert isinstance(result, RespondBlocks)
    assert result.start_height == uint32(0)
    assert result.end_height == uint32(0)
    assert result.blocks == [test_block]
    # After completion both sides should have properly updated their
    # in-flight windows.
    assert receiver_rl_window.receive_window == 0
    assert sender_rl_window.congestion_window == 0
    # Fill all slots concurrently
    max_concurrent = rate_limits_v3[msg_type].window_size
    tasks = [
        create_referenced_task(
            sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
        )
        for _ in range(max_concurrent)
    ]
    results = await asyncio.gather(*tasks)
    for result in results:
        assert isinstance(result, RespondBlocks)
        assert result.start_height == uint32(0)
        assert result.end_height == uint32(0)
        assert result.blocks == [test_block]
    assert receiver_rl_window.receive_window == 0
    assert sender_rl_window.congestion_window == 0
    # Check that the reject path also frees slots properly
    result = await sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(1), uint32(0), False))
    assert isinstance(result, RejectBlocks)
    assert result.start_height == uint32(1)
    assert result.end_height == uint32(0)
    assert receiver_rl_window.receive_window == 0
    assert sender_rl_window.congestion_window == 0
    # Issue a request back to the sender from the receiver
    result = await receiver_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(1), uint32(0), False))
    assert isinstance(result, RejectBlocks)
    assert result.start_height == uint32(1)
    assert result.end_height == uint32(0)
    assert sender_rl_window.receive_window == 0
    assert not sender_connection.closed
    assert not receiver_connection.closed
