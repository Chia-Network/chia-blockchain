from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
from chia_rs.sized_ints import uint32

from chia._tests.conftest import node_with_params
from chia._tests.util.misc import boolean_datacases
from chia._tests.util.time_out_assert import time_out_assert
from chia.protocols.full_node_protocol import RejectBlock, RejectBlocks, RespondBlock, RespondBlocks
from chia.protocols.outbound_message import make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.server.rate_limit_numbers import RLSettings, compose_rate_limits, get_rate_limits_to_use
from chia.server.rate_limit_numbers import rate_limits as rl_numbers
from chia.server.rate_limits import RateLimiter
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.peer_info import PeerInfo

rl_v2 = [Capability.BASE, Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2]
rl_v1 = [Capability.BASE]
node_with_params_b = node_with_params
test_different_versions_results: list[int] = []


@dataclass
class SimClock:
    current_time: float = 1000.0

    def monotonic(self) -> float:
        return self.current_time

    def advance(self, duration: float) -> None:
        self.current_time += duration


@pytest.mark.anyio
async def test_get_rate_limits_to_use() -> None:
    assert get_rate_limits_to_use(rl_v2, rl_v2) != get_rate_limits_to_use(rl_v2, rl_v1)
    assert get_rate_limits_to_use(rl_v1, rl_v1) == get_rate_limits_to_use(rl_v2, rl_v1)
    assert get_rate_limits_to_use(rl_v1, rl_v1) == get_rate_limits_to_use(rl_v1, rl_v2)


# we want to exercise every possibly limit we may hit
# they are:
# * total number of messages / 60 seconds for non-transaction messages
# * total number of bytes / 60 seconds for non-transaction messages
# * number of messages / 60 seconds for "transaction" messages
# * number of bytes / 60 seconds for transaction messages


@pytest.mark.anyio
@boolean_datacases(name="incoming", true="incoming", false="outgoing")
@boolean_datacases(name="tx_msg", true="tx", false="non-tx")
@boolean_datacases(name="limit_size", true="size-limit", false="count-limit")
async def test_limits_v2(incoming: bool, tx_msg: bool, limit_size: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    # this test uses a single message type, and alters the rate limit settings
    # for it to hit the different cases

    count = 1000
    message_data = b"\0" * 1024
    msg_type = ProtocolMessageTypes.new_transaction

    limits: dict[str, Any] = {}

    if limit_size:
        limits.update(
            {
                # this is the rate limit across all (non-tx) messages
                "non_tx_freq": count * 2,
                # this is the byte size limit across all (non-tx) messages
                "non_tx_max_total_size": count * len(message_data),
            }
        )
    else:
        limits.update(
            {
                # this is the rate limit across all (non-tx) messages
                "non_tx_freq": count,
                # this is the byte size limit across all (non-tx) messages
                "non_tx_max_total_size": count * 2 * len(message_data),
            }
        )

    if limit_size:
        rate_limit = {msg_type: RLSettings(count * 2, 1024, count * len(message_data))}
    else:
        rate_limit = {msg_type: RLSettings(count, 1024, count * 2 * len(message_data))}

    if tx_msg:
        limits.update({"rate_limits_tx": rate_limit, "rate_limits_other": {}})
    else:
        limits.update({"rate_limits_other": rate_limit, "rate_limits_tx": {}})

    def mock_get_limits(our_capabilities: list[Capability], peer_capabilities: list[Capability]) -> dict[str, Any]:
        return limits

    import chia.server.rate_limits

    monkeypatch.setattr(chia.server.rate_limits, "get_rate_limits_to_use", mock_get_limits)

    r = RateLimiter(incoming=incoming, get_time=lambda: 0)
    msg = make_msg(msg_type, message_data)

    for i in range(count):
        assert r.process_msg_and_check(msg, rl_v2, rl_v2) is None

    expected_msg = ""

    if limit_size:
        if not tx_msg:
            expected_msg += "non-tx size:"
        else:
            expected_msg += "cumulative size:"
        expected_msg += f" {(count + 1) * len(message_data)} > {count * len(message_data) * 1.0}"
    else:
        if not tx_msg:
            expected_msg += "non-tx count:"
        else:
            expected_msg += "message count:"
        expected_msg += f" {count + 1} > {count * 1.0}"
    expected_msg += " (scale factor: 1.0)"

    response = r.process_msg_and_check(msg, rl_v2, rl_v2)
    assert response == expected_msg

    for _ in range(10):
        response = r.process_msg_and_check(msg, rl_v2, rl_v2)
        # we can't stop incoming messages from arriving, counters keep
        # increasing for incoming messages. For outgoing messages, we expect
        # them not to be sent when hitting the rate limit, so those counters in
        # the returned message stay the same
        if incoming:
            assert response is not None
        else:
            assert response == expected_msg


@pytest.mark.anyio
async def test_large_message() -> None:
    # Large tx
    small_tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
    large_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 3 * 1024 * 1024))

    r = RateLimiter(incoming=True, get_time=lambda: 0)
    assert r.process_msg_and_check(small_tx_message, rl_v2, rl_v2) is None
    assert r.process_msg_and_check(large_tx_message, rl_v2, rl_v2) is not None

    small_vdf_message = make_msg(ProtocolMessageTypes.respond_signage_point, bytes([1] * 5 * 1024))
    large_vdf_message = make_msg(ProtocolMessageTypes.respond_signage_point, bytes([1] * 600 * 1024))
    large_blocks_message = make_msg(ProtocolMessageTypes.respond_blocks, bytes([1] * 51 * 1024 * 1024))
    r = RateLimiter(incoming=True, get_time=lambda: 0)
    assert r.process_msg_and_check(small_vdf_message, rl_v2, rl_v2) is None
    assert r.process_msg_and_check(small_vdf_message, rl_v2, rl_v2) is None
    assert r.process_msg_and_check(large_vdf_message, rl_v2, rl_v2) is not None
    # this limit applies even though this message type is unlimited
    assert r.process_msg_and_check(large_blocks_message, rl_v2, rl_v2) is not None


@pytest.mark.anyio
async def test_too_much_data() -> None:
    # Too much data
    r = RateLimiter(incoming=True, get_time=lambda: 0)
    tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
    for i in range(40):
        assert r.process_msg_and_check(tx_message, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(300):
        response = r.process_msg_and_check(tx_message, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect

    r = RateLimiter(incoming=True, get_time=lambda: 0)
    block_message = make_msg(ProtocolMessageTypes.respond_unfinished_block, bytes([1] * 1024 * 1024))
    for i in range(10):
        assert r.process_msg_and_check(block_message, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(40):
        response = r.process_msg_and_check(block_message, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect


@pytest.mark.anyio
async def test_non_tx_aggregate_limits() -> None:
    # Frequency limits
    r = RateLimiter(incoming=True, get_time=lambda: 0)
    message_1 = make_msg(ProtocolMessageTypes.coin_state_update, bytes([1] * 32))
    message_2 = make_msg(ProtocolMessageTypes.request_blocks, bytes([1] * 64))
    message_3 = make_msg(ProtocolMessageTypes.plot_sync_start, bytes([1] * 64))

    for i in range(500):
        assert r.process_msg_and_check(message_1, rl_v2, rl_v2) is None

    for i in range(500):
        assert r.process_msg_and_check(message_2, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(500):
        response = r.process_msg_and_check(message_3, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect

    # Size limits
    r = RateLimiter(incoming=True, get_time=lambda: 0)
    message_4 = make_msg(ProtocolMessageTypes.respond_proof_of_weight, bytes([1] * 49 * 1024 * 1024))
    message_5 = make_msg(ProtocolMessageTypes.request_blocks, bytes([1] * 49 * 1024 * 1024))

    for i in range(2):
        assert r.process_msg_and_check(message_4, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(2):
        response = r.process_msg_and_check(message_5, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect


@pytest.mark.anyio
async def test_periodic_reset() -> None:
    timer = SimClock()
    r = RateLimiter(True, 5, get_time=timer.monotonic)
    tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
    for i in range(10):
        assert r.process_msg_and_check(tx_message, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(300):
        response = r.process_msg_and_check(tx_message, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect
    assert r.process_msg_and_check(tx_message, rl_v2, rl_v2) is not None
    timer.advance(6)
    assert r.process_msg_and_check(tx_message, rl_v2, rl_v2) is None

    # Counts reset also
    r = RateLimiter(True, 5, get_time=timer.monotonic)
    new_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 40))
    for i in range(4999):
        assert r.process_msg_and_check(new_tx_message, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(4999):
        response = r.process_msg_and_check(new_tx_message, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect
    timer.advance(6)
    assert r.process_msg_and_check(new_tx_message, rl_v2, rl_v2) is None


@pytest.mark.anyio
async def test_percentage_limits() -> None:
    r = RateLimiter(True, 60, 40, get_time=lambda: 0)
    new_peak_message = make_msg(ProtocolMessageTypes.new_peak, bytes([1] * 40))
    for i in range(50):
        assert r.process_msg_and_check(new_peak_message, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(50):
        response = r.process_msg_and_check(new_peak_message, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect

    r = RateLimiter(True, 60, 40, get_time=lambda: 0)
    block_message = make_msg(ProtocolMessageTypes.respond_unfinished_block, bytes([1] * 1024 * 1024))
    for i in range(5):
        assert r.process_msg_and_check(block_message, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(5):
        response = r.process_msg_and_check(block_message, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect

    # Aggregate percentage limit count
    r = RateLimiter(True, 60, 40, get_time=lambda: 0)
    message_1 = make_msg(ProtocolMessageTypes.coin_state_update, bytes([1] * 5))
    message_2 = make_msg(ProtocolMessageTypes.request_blocks, bytes([1] * 32))
    message_3 = make_msg(ProtocolMessageTypes.plot_sync_start, bytes([1] * 32))

    for i in range(180):
        assert r.process_msg_and_check(message_1, rl_v2, rl_v2) is None
    for i in range(180):
        assert r.process_msg_and_check(message_2, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(100):
        response = r.process_msg_and_check(message_3, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect

    # Aggregate percentage limit max total size
    r = RateLimiter(True, 60, 40, get_time=lambda: 0)
    message_4 = make_msg(ProtocolMessageTypes.respond_proof_of_weight, bytes([1] * 18 * 1024 * 1024))
    message_5 = make_msg(ProtocolMessageTypes.respond_unfinished_block, bytes([1] * 24 * 1024 * 1024))

    for i in range(2):
        assert r.process_msg_and_check(message_4, rl_v2, rl_v2) is None

    saw_disconnect = False
    for i in range(2):
        response = r.process_msg_and_check(message_5, rl_v2, rl_v2)
        if response is not None:
            saw_disconnect = True
    assert saw_disconnect


@pytest.mark.anyio
async def test_too_many_outgoing_messages() -> None:
    # Too many messages
    r = RateLimiter(incoming=False, get_time=lambda: 0)
    new_peers_message = make_msg(ProtocolMessageTypes.respond_peers, bytes([1]))
    non_tx_freq = get_rate_limits_to_use(rl_v2, rl_v2)["non_tx_freq"]

    passed = 0
    blocked = 0
    for i in range(non_tx_freq):
        if r.process_msg_and_check(new_peers_message, rl_v2, rl_v2) is None:
            passed += 1
        else:
            blocked += 1

    assert passed == 10
    assert blocked == non_tx_freq - passed

    # ensure that *another* message type is not blocked because of this

    new_signatures_message = make_msg(ProtocolMessageTypes.respond_signatures, bytes([1]))
    assert r.process_msg_and_check(new_signatures_message, rl_v2, rl_v2) is None


@pytest.mark.anyio
async def test_too_many_incoming_messages() -> None:
    # Too many messages
    r = RateLimiter(incoming=True, get_time=lambda: 0)
    new_peers_message = make_msg(ProtocolMessageTypes.respond_peers, bytes([1]))
    non_tx_freq = get_rate_limits_to_use(rl_v2, rl_v2)["non_tx_freq"]

    passed = 0
    blocked = 0
    for i in range(non_tx_freq):
        if r.process_msg_and_check(new_peers_message, rl_v2, rl_v2) is None:
            passed += 1
        else:
            blocked += 1

    assert passed == 10
    assert blocked == non_tx_freq - passed

    # ensure that other message types *are* blocked because of this

    new_signatures_message = make_msg(ProtocolMessageTypes.respond_signatures, bytes([1]))
    assert r.process_msg_and_check(new_signatures_message, rl_v2, rl_v2) is not None


@pytest.mark.parametrize(
    "node_with_params",
    [
        pytest.param(
            dict(
                disable_capabilities=[Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2],
            ),
            id="V1",
        ),
        pytest.param(
            dict(
                disable_capabilities=[],
            ),
            id="V2",
        ),
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "node_with_params_b",
    [
        pytest.param(
            dict(
                disable_capabilities=[Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2],
            ),
            id="V1",
        ),
        pytest.param(
            dict(
                disable_capabilities=[],
            ),
            id="V2",
        ),
    ],
    indirect=True,
)
@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_different_versions(
    node_with_params: FullNodeSimulator, node_with_params_b: FullNodeSimulator, self_hostname: str
) -> None:
    node_a = node_with_params
    node_b = node_with_params_b

    full_node_server_a: ChiaServer = node_a.full_node.server
    full_node_server_b: ChiaServer = node_b.full_node.server

    await full_node_server_b.start_client(PeerInfo(self_hostname, full_node_server_a.get_port()), None)

    assert len(full_node_server_b.get_connections()) == 1
    assert len(full_node_server_a.get_connections()) == 1

    a_con: WSChiaConnection = full_node_server_a.get_connections()[0]
    b_con: WSChiaConnection = full_node_server_b.get_connections()[0]

    print(a_con.local_capabilities, a_con.peer_capabilities)
    print(b_con.local_capabilities, b_con.peer_capabilities)

    # The two nodes will use the same rate limits even if their versions are different
    assert get_rate_limits_to_use(a_con.local_capabilities, a_con.peer_capabilities) == get_rate_limits_to_use(
        b_con.local_capabilities, b_con.peer_capabilities
    )

    # The following code checks whether all of the runs resulted in the same number of items in "rate_limits_tx",
    # which would mean the same rate limits are always used. This should not happen, since two nodes with V2
    # will use V2.
    total_tx_msg_count = len(
        get_rate_limits_to_use(a_con.local_capabilities, a_con.peer_capabilities)["rate_limits_tx"]
    )

    test_different_versions_results.append(total_tx_msg_count)
    if len(test_different_versions_results) >= 4:
        assert len(set(test_different_versions_results)) >= 2


@pytest.mark.anyio
async def test_compose() -> None:
    rl_1 = rl_numbers[1]
    rl_2 = rl_numbers[2]
    rl_1_rate_limits_other = cast(dict[ProtocolMessageTypes, RLSettings], rl_1["rate_limits_other"])
    rl_2_rate_limits_other = cast(dict[ProtocolMessageTypes, RLSettings], rl_2["rate_limits_other"])
    rl_1_rate_limits_tx = cast(dict[ProtocolMessageTypes, RLSettings], rl_1["rate_limits_tx"])
    rl_2_rate_limits_tx = cast(dict[ProtocolMessageTypes, RLSettings], rl_2["rate_limits_tx"])
    assert ProtocolMessageTypes.respond_children in rl_1_rate_limits_other
    assert ProtocolMessageTypes.respond_children not in rl_1_rate_limits_tx
    assert ProtocolMessageTypes.respond_children not in rl_2_rate_limits_other
    assert ProtocolMessageTypes.respond_children in rl_2_rate_limits_tx

    assert ProtocolMessageTypes.request_block in rl_1_rate_limits_other
    assert ProtocolMessageTypes.request_block not in rl_1_rate_limits_tx
    assert ProtocolMessageTypes.request_block not in rl_2_rate_limits_other
    assert ProtocolMessageTypes.request_block not in rl_2_rate_limits_tx

    comps = compose_rate_limits(rl_1, rl_2)
    # v2 limits are used if present
    assert ProtocolMessageTypes.respond_children not in comps["rate_limits_other"]
    assert ProtocolMessageTypes.respond_children in comps["rate_limits_tx"]

    # Otherwise, fall back to v1
    assert ProtocolMessageTypes.request_block in rl_1_rate_limits_other
    assert ProtocolMessageTypes.request_block not in rl_1_rate_limits_tx


@pytest.mark.anyio
@pytest.mark.parametrize(
    "msg_type, size",
    [
        (ProtocolMessageTypes.respond_blocks, 10 * 1024 * 1024),
        (ProtocolMessageTypes.reject_blocks, 90),
        (ProtocolMessageTypes.respond_block, 1024 * 1024),
        (ProtocolMessageTypes.reject_block, 90),
    ],
)
async def test_unlimited(msg_type: ProtocolMessageTypes, size: int) -> None:
    r = RateLimiter(incoming=False, get_time=lambda: 0)

    message = make_msg(msg_type, bytes([1] * size))

    for i in range(1000):
        # since this is a backwards compatible change, it also affects V1
        assert r.process_msg_and_check(message, rl_v1, rl_v1) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "msg_type",
    [
        ProtocolMessageTypes.respond_blocks,
        ProtocolMessageTypes.reject_blocks,
        ProtocolMessageTypes.respond_block,
        ProtocolMessageTypes.reject_block,
    ],
)
@pytest.mark.parametrize(
    "node_with_params",
    [
        pytest.param(
            dict(
                disable_capabilities=[Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2],
            ),
            id="V1",
        ),
        pytest.param(
            dict(
                disable_capabilities=[],
            ),
            id="V2",
        ),
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "node_with_params_b",
    [
        pytest.param(
            dict(
                disable_capabilities=[Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2],
            ),
            id="V1",
        ),
        pytest.param(
            dict(
                disable_capabilities=[],
            ),
            id="V2",
        ),
    ],
    indirect=True,
)
async def test_unsolicited_responses(
    node_with_params: FullNodeSimulator,
    node_with_params_b: FullNodeSimulator,
    self_hostname: str,
    msg_type: ProtocolMessageTypes,
    bt: BlockTools,
) -> None:
    node_a = node_with_params
    node_b = node_with_params_b

    msg = {
        ProtocolMessageTypes.respond_blocks: make_msg(
            ProtocolMessageTypes.respond_blocks, bytes(RespondBlocks(uint32(1), uint32(2), []))
        ),
        ProtocolMessageTypes.reject_blocks: make_msg(
            ProtocolMessageTypes.reject_blocks, bytes(RejectBlocks(uint32(1), uint32(2)))
        ),
        ProtocolMessageTypes.respond_block: make_msg(
            ProtocolMessageTypes.respond_block, bytes(RespondBlock(bt.get_consecutive_blocks(1)[0]))
        ),
        ProtocolMessageTypes.reject_block: make_msg(ProtocolMessageTypes.reject_block, bytes(RejectBlock(uint32(0)))),
    }[msg_type]

    full_node_server_a: ChiaServer = node_a.full_node.server
    full_node_server_b: ChiaServer = node_b.full_node.server

    await full_node_server_b.start_client(PeerInfo(self_hostname, full_node_server_a.get_port()), None)

    assert len(full_node_server_b.get_connections()) == 1
    assert len(full_node_server_a.get_connections()) == 1

    a_con: WSChiaConnection = full_node_server_a.get_connections()[0]
    b_con: WSChiaConnection = full_node_server_b.get_connections()[0]

    assert not a_con.closed
    assert not b_con.closed

    await a_con.send_message(msg)

    # make sure the connection is closed because of the unsolicited response
    # message
    await time_out_assert(5, lambda: a_con.closed)
