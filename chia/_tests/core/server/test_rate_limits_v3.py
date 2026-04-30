from __future__ import annotations

import asyncio
import logging

import pytest
from chia_rs import RespondToPhUpdates
from chia_rs.sized_ints import uint8, uint16, uint32

from chia._tests.conftest import ConsensusMode
from chia._tests.connection_utils import add_dummy_connection_wsc
from chia._tests.util import network_protocol_data
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import (
    RejectBlocks,
    RequestBlocks,
    RespondBlocks,
)
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability, ConfigureWindowSizes, default_capabilities
from chia.server.rate_limits_v3 import (
    MAX_CONFIGURE_RATE_LIMITS_ENTRIES,
    RLSettingsV3,
    rate_limits_v3,
    rl_settings_v3_from_configure_message,
    rl_v3_to_configure_message,
)
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.peer_info import PeerInfo
from chia.util.streamable import Streamable
from chia.util.task_referencer import create_referenced_task


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {
            ProtocolMessageTypes.request_blocks: RLSettingsV3(window_size=2),
            ProtocolMessageTypes.request_block: RLSettingsV3(window_size=1),
        },
    ],
)
def test_rl_v3_roundtrip(settings: dict[ProtocolMessageTypes, RLSettingsV3] | None) -> None:
    """
    Encode a `ConfigureWindowSizes` settings map into a message then parse it
    back to make sure that works properly.
    """
    msg = rl_v3_to_configure_message(settings=settings)
    parsed = rl_settings_v3_from_configure_message(msg)
    expected_settings = rate_limits_v3 if settings is None else settings
    assert parsed == expected_settings
    actual_map: dict[int, int] = {}
    for msg_type_val, window_size_val in msg.settings:
        actual_map[int(msg_type_val)] = int(window_size_val)
    expected_map = {
        msg_type.value: 0 if setting.window_size is None else setting.window_size
        for msg_type, setting in expected_settings.items()
    }
    assert actual_map == expected_map
    for msg_type, setting in expected_settings.items():
        if setting.window_size is None:
            assert actual_map[msg_type.value] == 0
        else:
            assert actual_map[msg_type.value] == setting.window_size


def test_rl_settings_v3_from_configure_message() -> None:
    """
    Covers `rl_settings_v3_from_configure_message` to make sure partial
    overrides, unknown types, and zero (unlimited) values are handled.
    """
    test_message_type = ProtocolMessageTypes.request_blocks
    test_message_type2 = ProtocolMessageTypes.request_block
    # Partial list: only the explicitly sent type is present
    msg = ConfigureWindowSizes(settings=[(uint8(test_message_type.value), uint16(5))])
    parsed = rl_settings_v3_from_configure_message(msg)
    assert parsed[test_message_type].window_size == 5
    assert test_message_type2 not in parsed
    # Multiple entries
    msg = ConfigureWindowSizes(
        settings=[(uint8(test_message_type.value), uint16(4)), (uint8(test_message_type2.value), uint16(5))]
    )
    parsed = rl_settings_v3_from_configure_message(msg)
    assert parsed == {test_message_type: RLSettingsV3(window_size=4), test_message_type2: RLSettingsV3(window_size=5)}
    # Zero value is treated as unlimited
    msg = ConfigureWindowSizes(settings=[(uint8(test_message_type.value), uint16(0))])
    parsed = rl_settings_v3_from_configure_message(msg)
    assert parsed[test_message_type].window_size is None
    # Message types not in our global defaults should be accepted
    peer_only_message_type = ProtocolMessageTypes.request_signatures
    assert peer_only_message_type not in rate_limits_v3
    msg = ConfigureWindowSizes(
        settings=[(uint8(peer_only_message_type.value), uint16(5)), (uint8(test_message_type.value), uint16(4))]
    )
    parsed = rl_settings_v3_from_configure_message(msg)
    assert parsed[test_message_type].window_size == 4
    assert parsed[peer_only_message_type].window_size == 5
    # Invalid message type (value 2 has no ProtocolMessageTypes member) is skipped
    msg = ConfigureWindowSizes(settings=[(uint8(2), uint16(5)), (uint8(test_message_type.value), uint16(4))])
    parsed = rl_settings_v3_from_configure_message(msg)
    assert parsed[test_message_type].window_size == 4
    assert len(parsed) == 1
    # Unlimited value altered
    unlimited_message_type = next(
        msg_type for msg_type, setting in rate_limits_v3.items() if setting.window_size is None
    )
    msg = ConfigureWindowSizes(settings=[(uint8(unlimited_message_type.value), uint16(42))])
    with pytest.raises(Exception, match="Error code: INVALID_HANDSHAKE"):
        rl_settings_v3_from_configure_message(msg)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("config_settings_length", [0, MAX_CONFIGURE_RATE_LIMITS_ENTRIES + 1])
async def test_invalid_config_settings_length(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    config_settings_length: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where a peer sends a `ConfigureWindowSizes` message with
    an invalid number of settings entries.
    """
    settings = [(uint8(ProtocolMessageTypes.request_blocks.value), uint16(1))] * config_settings_length
    monkeypatch.setattr(
        "chia.server.ws_connection.rl_v3_to_configure_message", lambda: ConfigureWindowSizes(settings=settings)
    )
    _, server, _ = one_node_one_block
    with pytest.raises(Exception, match="INVALID_HANDSHAKE"):
        await add_dummy_connection_wsc(server, self_hostname, 1337)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("receiver_v3_enabled", [False, True])
@pytest.mark.parametrize("sender_v3_enabled", [False, True])
async def test_separate_config_msg(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    receiver_v3_enabled: bool,
    sender_v3_enabled: bool,
) -> None:
    """
    Covers the scenario where we send `configure_window_sizes` message outside
    the context of a handshake.
    """
    _, server, _ = one_node_one_block
    # Control what the server advertises in its handshake.
    server_capabilities = list(default_capabilities[NodeType.FULL_NODE])
    if receiver_v3_enabled:
        server_capabilities.append((uint16(Capability.RATE_LIMITS_V3.value), "1"))
    server.set_capabilities(server_capabilities)
    # Control what the client advertises in its handshake.
    sender_capabilities: list[tuple[uint16, str]] = [(uint16(Capability.HARD_FORK_2.value), "1")]
    if sender_v3_enabled:
        sender_capabilities.append((uint16(Capability.RATE_LIMITS_V3.value), "1"))
    sender_connection, peer_id = await add_dummy_connection_wsc(
        server, self_hostname, 42, additional_capabilities=sender_capabilities
    )
    server.all_connections[peer_id].peer_info = PeerInfo("1.3.3.7", 42)
    await sender_connection.send_message(
        make_msg(
            ProtocolMessageTypes.configure_window_sizes, ConfigureWindowSizes(settings=[(uint8(42), uint16(1337))])
        )
    )
    await time_out_assert(5, lambda: sender_connection.closed)
    await time_out_assert(5, lambda: "1.3.3.7" in server.banned_peers)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_malformed_config_message_bytes(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where we send malformed data in the rate limits v3
    configuration message.
    """
    _, server, _ = one_node_one_block
    malformed_config_msg = make_msg(ProtocolMessageTypes.configure_window_sizes, b"42")
    original_send_message = WSChiaConnection._send_message

    async def test_send_message(self: WSChiaConnection, message: Message, priority: int = 0) -> None:
        # Intercept the config message sent by the peer to set malformed data
        if self.is_outbound and ProtocolMessageTypes(message.type) == ProtocolMessageTypes.configure_window_sizes:
            message = malformed_config_msg
        await original_send_message(self, message)

    monkeypatch.setattr(WSChiaConnection, "_send_message", test_send_message)
    sender_connection, _ = await add_dummy_connection_wsc(server, self_hostname, 1337, wait_for_peer_added=False)
    await time_out_assert(5, lambda: sender_connection.closed)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_non_config_msg_during_handshake(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario where we receive a message other than the expected
    `configure_window_sizes` message during the handshake.
    """
    _, server, _ = one_node_one_block
    random_non_config_msg = make_msg(ProtocolMessageTypes.request_blocks, b"")
    original_send_message = WSChiaConnection._send_message

    async def test_send_message(self: WSChiaConnection, message: Message, priority: int = 0) -> None:
        # Intercept the config message sent by the peer to send an unexpected
        # message instead.
        if self.is_outbound and ProtocolMessageTypes(message.type) == ProtocolMessageTypes.configure_window_sizes:
            message = random_non_config_msg
        await original_send_message(self, message)

    monkeypatch.setattr(WSChiaConnection, "_send_message", test_send_message)
    sender_connection, _ = await add_dummy_connection_wsc(server, self_hostname, 1337, wait_for_peer_added=False)
    await time_out_assert(5, lambda: sender_connection.closed)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_unsolicited_unlimited_v3_messages(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools], self_hostname: str
) -> None:
    """
    Covers v3 response message types to make sure unsolicited messages of those
    types get the peers disconnected/banned except `respond_proof_of_weight`.
    """
    unsolicited_messages: dict[ProtocolMessageTypes, Streamable | RespondToPhUpdates] = {
        ProtocolMessageTypes.respond_blocks: network_protocol_data.respond_blocks,
        ProtocolMessageTypes.reject_blocks: network_protocol_data.reject_blocks,
        ProtocolMessageTypes.respond_block: network_protocol_data.respond_block,
        ProtocolMessageTypes.reject_block: network_protocol_data.reject_block,
        ProtocolMessageTypes.respond_block_header: network_protocol_data.respond_header_block,
        ProtocolMessageTypes.reject_header_request: network_protocol_data.reject_header_request,
        ProtocolMessageTypes.respond_block_headers: network_protocol_data.respond_block_headers,
        ProtocolMessageTypes.reject_block_headers: network_protocol_data.reject_block_headers,
        ProtocolMessageTypes.respond_header_blocks: network_protocol_data.respond_header_blocks,
        ProtocolMessageTypes.reject_header_blocks: network_protocol_data.reject_header_blocks,
        ProtocolMessageTypes.respond_to_ph_updates: network_protocol_data.respond_to_ph_updates,
        ProtocolMessageTypes.respond_to_coin_updates: network_protocol_data.respond_to_coin_updates,
        ProtocolMessageTypes.respond_puzzle_state: network_protocol_data.respond_puzzle_state,
        ProtocolMessageTypes.reject_puzzle_state: network_protocol_data.reject_puzzle_state,
        ProtocolMessageTypes.respond_coin_state: network_protocol_data.respond_coin_state,
        ProtocolMessageTypes.reject_coin_state: network_protocol_data.reject_coin_state,
        ProtocolMessageTypes.respond_additions: network_protocol_data.respond_additions,
        ProtocolMessageTypes.reject_additions_request: network_protocol_data.reject_additions,
        ProtocolMessageTypes.respond_removals: network_protocol_data.respond_removals,
        ProtocolMessageTypes.reject_removals_request: network_protocol_data.reject_removals_request,
        ProtocolMessageTypes.respond_proof_of_weight: network_protocol_data.respond_proof_of_weight,
        ProtocolMessageTypes.respond_puzzle_solution: network_protocol_data.respond_puzzle_solution,
        ProtocolMessageTypes.reject_puzzle_solution: network_protocol_data.reject_puzzle_solution,
    }
    expected_unlimited = {msg_type for msg_type, settings in rate_limits_v3.items() if settings.window_size is None}
    current_unlimited = set(unsolicited_messages)
    assert current_unlimited == expected_unlimited
    _, server, _ = one_node_one_block
    test_host = "1.3.3.7"
    for msg_type, msg_data in unsolicited_messages.items():
        if msg_type == ProtocolMessageTypes.respond_proof_of_weight:
            # This one doesn't disconnect/ban the peer
            continue
        sender_connection, peer_id = await add_dummy_connection_wsc(server, self_hostname, dummy_port=msg_type.value)
        receiver_connection = server.all_connections[peer_id]
        receiver_connection.peer_info = PeerInfo(test_host, receiver_connection.peer_info.port)
        server.banned_peers.pop(test_host, None)
        assert test_host not in server.banned_peers
        await sender_connection.send_message(make_msg(msg_type, msg_data))
        await time_out_assert(5, lambda: sender_connection.closed)
        await time_out_assert(5, lambda: test_host in server.banned_peers)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("receiver_v3_enabled", [False, True])
@pytest.mark.parametrize("sender_v3_enabled", [False, True])
async def test_v3_init_and_v2_fallback(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    receiver_v3_enabled: bool,
    sender_v3_enabled: bool,
) -> None:
    """
    Covers the scenario where we connect to a peer using all combinations of v2
    and v3 capability cases: one side is v3 and the other is v2, both are v2
    and both are v3.
    We make sure that each side properly sees the other's v3 capability
    advertisement and correctly parses the peer's v3 config into
    `peer_rl_settings_v3`.
    When the peer doesn't support v3 we make sure to fall back to the v2 rate limiter.
    We also make sure the v3 windows are initialized for all v3 message types.
    NOTE: If the sender advertises support for v3, the receiver will advertise
    support for v3 as well.
    """
    _, server, _ = one_node_one_block
    # Control what the server advertises in its handshake.
    server_capabilities = list(default_capabilities[NodeType.FULL_NODE])
    if receiver_v3_enabled:
        server_capabilities.append((uint16(Capability.RATE_LIMITS_V3.value), "1"))
    server.set_capabilities(server_capabilities)
    # Control what the client advertises in its handshake.
    sender_capabilities: list[tuple[uint16, str]] = [(uint16(Capability.HARD_FORK_2.value), "1")]
    if sender_v3_enabled:
        sender_capabilities.append((uint16(Capability.RATE_LIMITS_V3.value), "1"))
    sender_connection, peer_id = await add_dummy_connection_wsc(
        server, self_hostname, 1337, additional_capabilities=sender_capabilities
    )
    sender_connection.peer_info = PeerInfo("1.3.3.7", sender_connection.peer_info.port)
    receiver_connection = server.all_connections[peer_id]
    receiver_connection.peer_info = PeerInfo("1.2.3.4", receiver_connection.peer_info.port)
    # Make sure the receiver sees exactly what the sender advertised
    assert (Capability.RATE_LIMITS_V3 in receiver_connection.peer_capabilities) == sender_v3_enabled
    # Make sure the sender sees what the receiver advertised in reply, it can
    # end up advertising v3 support either because it's enabled in its setup or
    # in reaction to the sender advertising support for it (even if it's
    # disabled in its setup).
    receiver_advertised_v3 = receiver_v3_enabled or sender_v3_enabled
    assert (Capability.RATE_LIMITS_V3 in sender_connection.peer_capabilities) == receiver_advertised_v3
    both_v3 = sender_v3_enabled
    # Make sure the parsed v3 config matches what the other side advertised
    assert receiver_connection.peer_rl_settings_v3 == (rate_limits_v3 if both_v3 else {})
    assert sender_connection.peer_rl_settings_v3 == (rate_limits_v3 if both_v3 else {})
    # Rate limit windows should always be initialized for all supported v3
    # message types.
    for msg_type, settings in rate_limits_v3.items():
        if settings.window_size is None:
            continue
        rl_window = receiver_connection.rate_limit_windows.get(msg_type)
        assert rl_window is not None
        assert rl_window.receive_window == 0
        assert rl_window.in_flight == 0


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("window_size", [None, 2])
async def test_receiving_unknown_msg_type_in_config(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    window_size: int | None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Covers the scenario where we receive a `ConfigureWindowSizes` message with a
    protocol message type that we don't have in our rate limits config, to make
    sure we parse it and track it properly via the provided window size, and if
    that's unlimited then we don't rate limit ourselves accordingly.
    """
    _, server, _ = one_node_one_block
    unknown_type_to_us = ProtocolMessageTypes.request_peers
    assert unknown_type_to_us not in rate_limits_v3
    config_settings = dict(rate_limits_v3)
    config_settings[unknown_type_to_us] = RLSettingsV3(window_size=window_size)
    config_msg_with_unknown_type = make_msg(
        ProtocolMessageTypes.configure_window_sizes, rl_v3_to_configure_message(settings=config_settings)
    )
    original_send_message = WSChiaConnection._send_message

    async def test_send_message(self: WSChiaConnection, message: Message, priority: int = 0) -> None:
        # Intercept the config message sent by the peer to add to it the
        # message type that is unknown to us.
        if self.is_outbound and ProtocolMessageTypes(message.type) == ProtocolMessageTypes.configure_window_sizes:
            message = config_msg_with_unknown_type
        await original_send_message(self, message)

    monkeypatch.setattr(WSChiaConnection, "_send_message", test_send_message)
    sender_connection, peer_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
    sender_connection.peer_info = PeerInfo("1.3.3.7", sender_connection.peer_info.port)
    receiver_connection = server.all_connections[peer_id]
    receiver_connection.peer_info = PeerInfo("1.2.3.4", receiver_connection.peer_info.port)
    assert receiver_connection.peer_rl_settings_v3[unknown_type_to_us].window_size == window_size
    if window_size is None:
        # We don't track unlimited message types, we won't rate limit ourselves
        assert unknown_type_to_us not in receiver_connection.rate_limit_windows
    else:
        assert receiver_connection.rate_limit_windows[unknown_type_to_us].receive_window == 0
        assert receiver_connection.rate_limit_windows[unknown_type_to_us].in_flight == 0

    async def send_request_task() -> None:
        await receiver_connection.send_request(make_msg(unknown_type_to_us, b""), timeout=1)

    assert unknown_type_to_us not in sender_connection.rate_limit_windows
    caplog.set_level(logging.INFO)
    caplog.clear()
    # Send more requests than the window size when it's not None to make sure
    # we rate limit ourselves in that case and we don't when it's None.
    await asyncio.gather(*(send_request_task() for _ in range(3)))
    assert (
        f"Rate limiting ourselves (v3). Dropping and retrying outbound message: {unknown_type_to_us.name}"
        in caplog.text
    ) == (window_size is not None)


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
    receiver_connection1 = server.all_connections[sender_id]
    receiver_connection1.peer_info = PeerInfo("1.3.3.7", receiver_connection1.peer_info.port)
    sender_connection2, sender2_id = await add_dummy_connection_wsc(server, self_hostname, 1234)
    receiver_connection2 = server.all_connections[sender2_id]
    receiver_connection2.peer_info = PeerInfo("1.2.3.4", receiver_connection2.peer_info.port)
    localhost_sender, _ = await add_dummy_connection_wsc(server, self_hostname, 5678)
    msg_type = ProtocolMessageTypes.request_blocks
    release_handler = asyncio.Event()

    async def slow_handler(api: FullNodeAPI, request_bytes: bytes) -> Message | None:
        await release_handler.wait()
        return None

    request_blocks_api = receiver_connection1.api.metadata.message_type_to_request[msg_type]
    monkeypatch.setattr(request_blocks_api, "method", slow_handler)
    max_concurrent = rate_limits_v3[msg_type].window_size
    assert max_concurrent is not None

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
    assert max_concurrent is not None
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
    Covers the scenario where the peer fills the congestion window for a
    protocol request type, and further requests of that type get dropped and
    retried.
    With `server_custom_config` we control whether we advertise a custom
    window size via the ConfigureWindowSizes message and make sure the peer
    honours that value instead of the global default one.
    With `bigger_window_size` we control whether the custom config advertises
    a bigger or smaller window size than the default.
    """
    _, server, _ = one_node_one_block
    msg_type = ProtocolMessageTypes.request_blocks
    test_window_size = rate_limits_v3[msg_type].window_size
    assert test_window_size is not None
    if server_custom_config:
        # Configure a different window size
        test_window_size += 1 if bigger_window_size else -1
        # Update the server's global defaults and advertised v3 capability
        monkeypatch.setitem(rate_limits_v3, msg_type, RLSettingsV3(window_size=test_window_size))
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 1337)
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
    assert rl_window.in_flight == max_concurrent
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
    await time_out_assert(5, lambda: rl_window.in_flight == 0)
    # A fresh request should succeed
    result = await sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
    assert isinstance(result, RespondBlocks)
    assert rl_window.in_flight == 0


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
    assert sender_connection.rate_limit_windows[msg_type].in_flight == 0


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
async def test_unlimited_messages_bypass_v2_rl(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenario of v3 supported unlimited messages to make sure they're
    not subject to the v2 rate limiter.
    """
    _, server, _ = one_node_one_block
    sender_connection, sender_id = await add_dummy_connection_wsc(server, self_hostname, 42)
    sender_connection.peer_info = PeerInfo("1.3.3.7", sender_connection.peer_info.port)
    server_connection = server.all_connections[sender_id]
    server_connection.peer_info = PeerInfo("1.2.3.4", server_connection.peer_info.port)
    assert Capability.RATE_LIMITS_V3 in server_connection.peer_capabilities
    assert server_connection.peer_rl_settings_v3[ProtocolMessageTypes.respond_blocks].window_size is None

    def test_process_msg_and_check(
        message: Message, our_capabilities: list[Capability], peer_capabilities: list[Capability]
    ) -> str | None:
        # Make sure the v2 rate limiter didn't process the outbound response type
        assert False  # pragma: no cover

    monkeypatch.setattr(server_connection.outbound_rate_limiter, "process_msg_and_check", test_process_msg_and_check)
    result = await sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(0), uint32(0), False))
    assert isinstance(result, RespondBlocks)
    assert result.start_height == uint32(0)
    assert result.end_height == uint32(0)
    assert len(result.blocks) == 1
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
    receiver_connection = server.all_connections[sender_id]
    receiver_connection.peer_info = PeerInfo("1.3.3.7", receiver_connection.peer_info.port)
    sender_connection.peer_info = PeerInfo("1.2.3.4", sender_connection.peer_info.port)
    msg_type = ProtocolMessageTypes.request_blocks
    max_concurrent = rate_limits_v3[msg_type].window_size
    assert max_concurrent is not None
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
    assert rl_window.in_flight == max_concurrent
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
    await time_out_assert(5, lambda: rl_window.in_flight == 0)


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
@pytest.mark.parametrize("tracked_request", [False, True])
async def test_v3_messages_wrt_v2_rate_limiter(
    one_node_one_block: tuple[FullNodeSimulator, ChiaServer, BlockTools],
    self_hostname: str,
    tracked_request: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Covers the scenarios where we send a v3 supported protocol message to a
    peer that advertises RATE_LIMITS_V3, tracked (with nonce) and untracked, to
    make sure the v2 rate limiter gets properly bypassed/activated.
    """
    _, server, _ = one_node_one_block
    sender_connection, _ = await add_dummy_connection_wsc(server, self_hostname, 42)
    sender_connection.peer_info = PeerInfo("1.3.3.7", sender_connection.peer_info.port)
    event = asyncio.Event()
    processed_msgs: list[ProtocolMessageTypes] = []

    def test_process_msg_and_check(
        message: Message, our_capabilities: list[Capability], peer_capabilities: list[Capability]
    ) -> str | None:
        processed_msgs.append(ProtocolMessageTypes(message.type))
        event.set()
        return None

    monkeypatch.setattr(sender_connection.outbound_rate_limiter, "process_msg_and_check", test_process_msg_and_check)
    msg_type = ProtocolMessageTypes.request_blocks
    request = RequestBlocks(uint32(0), uint32(0), False)
    if tracked_request:
        # V2 rate limiter should not be invoked for v3 tracked messages
        response = await sender_connection.call_api(FullNodeAPI.request_blocks, request)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=1)
        assert msg_type not in processed_msgs
        assert isinstance(response, RespondBlocks)
        assert response.start_height == uint32(0)
        assert response.end_height == uint32(0)
        assert len(response.blocks) == 1
    else:
        # V2 rate limiter should be invoked for untracked messages
        await sender_connection.send_message(make_msg(msg_type, request))
        await asyncio.wait_for(event.wait(), timeout=1)
        assert msg_type in processed_msgs
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
    assert sender_rl_window.in_flight == 0
    # Fill all slots concurrently
    max_concurrent = rate_limits_v3[msg_type].window_size
    assert max_concurrent is not None
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
    assert sender_rl_window.in_flight == 0
    # Check that the reject path also frees slots properly
    result = await sender_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(1), uint32(0), False))
    assert isinstance(result, RejectBlocks)
    assert result.start_height == uint32(1)
    assert result.end_height == uint32(0)
    assert receiver_rl_window.receive_window == 0
    assert sender_rl_window.in_flight == 0
    # Issue a request back to the sender from the receiver
    result = await receiver_connection.call_api(FullNodeAPI.request_blocks, RequestBlocks(uint32(1), uint32(0), False))
    assert isinstance(result, RejectBlocks)
    assert result.start_height == uint32(1)
    assert result.end_height == uint32(0)
    assert sender_rl_window.receive_window == 0
    assert not sender_connection.closed
    assert not receiver_connection.closed
