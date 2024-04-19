from __future__ import annotations

import asyncio
from typing import List

import pytest

from chia._tests.conftest import node_with_params
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.server.outbound_message import make_msg
from chia.server.rate_limit_numbers import compose_rate_limits, get_rate_limits_to_use
from chia.server.rate_limit_numbers import rate_limits as rl_numbers
from chia.server.rate_limits import RateLimiter
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo

rl_v2 = [Capability.BASE, Capability.BLOCK_HEADERS, Capability.RATE_LIMITS_V2]
rl_v1 = [Capability.BASE]
node_with_params_b = node_with_params
test_different_versions_results: List[int] = []


class TestRateLimits:
    @pytest.mark.anyio
    async def test_get_rate_limits_to_use(self):
        assert get_rate_limits_to_use(rl_v2, rl_v2) != get_rate_limits_to_use(rl_v2, rl_v1)
        assert get_rate_limits_to_use(rl_v1, rl_v1) == get_rate_limits_to_use(rl_v2, rl_v1)
        assert get_rate_limits_to_use(rl_v1, rl_v1) == get_rate_limits_to_use(rl_v1, rl_v2)

    @pytest.mark.anyio
    async def test_too_many_messages(self):
        # Too many messages
        r = RateLimiter(incoming=True)
        new_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 40))
        for i in range(4999):
            assert r.process_msg_and_check(new_tx_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(4999):
            response = r.process_msg_and_check(new_tx_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Non-tx message
        r = RateLimiter(incoming=True)
        new_peak_message = make_msg(ProtocolMessageTypes.new_peak, bytes([1] * 40))
        for i in range(200):
            assert r.process_msg_and_check(new_peak_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(200):
            response = r.process_msg_and_check(new_peak_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

    @pytest.mark.anyio
    async def test_large_message(self):
        # Large tx
        small_tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
        large_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 3 * 1024 * 1024))

        r = RateLimiter(incoming=True)
        assert r.process_msg_and_check(small_tx_message, rl_v2, rl_v2)
        assert not r.process_msg_and_check(large_tx_message, rl_v2, rl_v2)

        small_vdf_message = make_msg(ProtocolMessageTypes.respond_signage_point, bytes([1] * 5 * 1024))
        large_vdf_message = make_msg(ProtocolMessageTypes.respond_signage_point, bytes([1] * 600 * 1024))
        r = RateLimiter(incoming=True)
        assert r.process_msg_and_check(small_vdf_message, rl_v2, rl_v2)
        assert r.process_msg_and_check(small_vdf_message, rl_v2, rl_v2)
        assert not r.process_msg_and_check(large_vdf_message, rl_v2, rl_v2)

    @pytest.mark.anyio
    async def test_too_much_data(self):
        # Too much data
        r = RateLimiter(incoming=True)
        tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
        for i in range(40):
            assert r.process_msg_and_check(tx_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(300):
            response = r.process_msg_and_check(tx_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        r = RateLimiter(incoming=True)
        block_message = make_msg(ProtocolMessageTypes.respond_block, bytes([1] * 1024 * 1024))
        for i in range(10):
            assert r.process_msg_and_check(block_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(40):
            response = r.process_msg_and_check(block_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

    @pytest.mark.anyio
    async def test_non_tx_aggregate_limits(self):
        # Frequency limits
        r = RateLimiter(incoming=True)
        message_1 = make_msg(ProtocolMessageTypes.coin_state_update, bytes([1] * 32))
        message_2 = make_msg(ProtocolMessageTypes.request_blocks, bytes([1] * 64))
        message_3 = make_msg(ProtocolMessageTypes.plot_sync_start, bytes([1] * 64))

        for i in range(500):
            assert r.process_msg_and_check(message_1, rl_v2, rl_v2)

        for i in range(500):
            assert r.process_msg_and_check(message_2, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(500):
            response = r.process_msg_and_check(message_3, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Size limits
        r = RateLimiter(incoming=True)
        message_4 = make_msg(ProtocolMessageTypes.respond_proof_of_weight, bytes([1] * 49 * 1024 * 1024))
        message_5 = make_msg(ProtocolMessageTypes.respond_blocks, bytes([1] * 49 * 1024 * 1024))

        for i in range(2):
            assert r.process_msg_and_check(message_4, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(2):
            response = r.process_msg_and_check(message_5, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

    @pytest.mark.anyio
    async def test_periodic_reset(self):
        r = RateLimiter(True, 5)
        tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
        for i in range(10):
            assert r.process_msg_and_check(tx_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(300):
            response = r.process_msg_and_check(tx_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect
        assert not r.process_msg_and_check(tx_message, rl_v2, rl_v2)
        await asyncio.sleep(6)
        assert r.process_msg_and_check(tx_message, rl_v2, rl_v2)

        # Counts reset also
        r = RateLimiter(True, 5)
        new_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 40))
        for i in range(4999):
            assert r.process_msg_and_check(new_tx_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(4999):
            response = r.process_msg_and_check(new_tx_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect
        await asyncio.sleep(6)
        assert r.process_msg_and_check(new_tx_message, rl_v2, rl_v2)

    @pytest.mark.anyio
    async def test_percentage_limits(self):
        r = RateLimiter(True, 60, 40)
        new_peak_message = make_msg(ProtocolMessageTypes.new_peak, bytes([1] * 40))
        for i in range(50):
            assert r.process_msg_and_check(new_peak_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(50):
            response = r.process_msg_and_check(new_peak_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        r = RateLimiter(True, 60, 40)
        block_message = make_msg(ProtocolMessageTypes.respond_block, bytes([1] * 1024 * 1024))
        for i in range(5):
            assert r.process_msg_and_check(block_message, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(5):
            response = r.process_msg_and_check(block_message, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Aggregate percentage limit count
        r = RateLimiter(True, 60, 40)
        message_1 = make_msg(ProtocolMessageTypes.coin_state_update, bytes([1] * 5))
        message_2 = make_msg(ProtocolMessageTypes.request_blocks, bytes([1] * 32))
        message_3 = make_msg(ProtocolMessageTypes.plot_sync_start, bytes([1] * 32))

        for i in range(180):
            assert r.process_msg_and_check(message_1, rl_v2, rl_v2)
        for i in range(180):
            assert r.process_msg_and_check(message_2, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(100):
            response = r.process_msg_and_check(message_3, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Aggregate percentage limit max total size
        r = RateLimiter(True, 60, 40)
        message_4 = make_msg(ProtocolMessageTypes.respond_proof_of_weight, bytes([1] * 18 * 1024 * 1024))
        message_5 = make_msg(ProtocolMessageTypes.respond_blocks, bytes([1] * 24 * 1024 * 1024))

        for i in range(2):
            assert r.process_msg_and_check(message_4, rl_v2, rl_v2)

        saw_disconnect = False
        for i in range(2):
            response = r.process_msg_and_check(message_5, rl_v2, rl_v2)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

    @pytest.mark.anyio
    async def test_too_many_outgoing_messages(self):
        # Too many messages
        r = RateLimiter(incoming=False)
        new_peers_message = make_msg(ProtocolMessageTypes.respond_peers, bytes([1]))
        non_tx_freq = get_rate_limits_to_use(rl_v2, rl_v2)["non_tx_freq"]

        passed = 0
        blocked = 0
        for i in range(non_tx_freq):
            if r.process_msg_and_check(new_peers_message, rl_v2, rl_v2):
                passed += 1
            else:
                blocked += 1

        assert passed == 10
        assert blocked == non_tx_freq - passed

        # ensure that *another* message type is not blocked because of this

        new_signatures_message = make_msg(ProtocolMessageTypes.respond_signatures, bytes([1]))
        assert r.process_msg_and_check(new_signatures_message, rl_v2, rl_v2)

    @pytest.mark.anyio
    async def test_too_many_incoming_messages(self):
        # Too many messages
        r = RateLimiter(incoming=True)
        new_peers_message = make_msg(ProtocolMessageTypes.respond_peers, bytes([1]))
        non_tx_freq = get_rate_limits_to_use(rl_v2, rl_v2)["non_tx_freq"]

        passed = 0
        blocked = 0
        for i in range(non_tx_freq):
            if r.process_msg_and_check(new_peers_message, rl_v2, rl_v2):
                passed += 1
            else:
                blocked += 1

        assert passed == 10
        assert blocked == non_tx_freq - passed

        # ensure that other message types *are* blocked because of this

        new_signatures_message = make_msg(ProtocolMessageTypes.respond_signatures, bytes([1]))
        assert not r.process_msg_and_check(new_signatures_message, rl_v2, rl_v2)

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
    async def test_different_versions(self, node_with_params, node_with_params_b, self_hostname):
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
    async def test_compose(self):
        rl_1 = rl_numbers[1]
        rl_2 = rl_numbers[2]
        assert ProtocolMessageTypes.respond_children in rl_1["rate_limits_other"]
        assert ProtocolMessageTypes.respond_children not in rl_1["rate_limits_tx"]
        assert ProtocolMessageTypes.respond_children not in rl_2["rate_limits_other"]
        assert ProtocolMessageTypes.respond_children in rl_2["rate_limits_tx"]

        assert ProtocolMessageTypes.request_block in rl_1["rate_limits_other"]
        assert ProtocolMessageTypes.request_block not in rl_1["rate_limits_tx"]
        assert ProtocolMessageTypes.request_block not in rl_2["rate_limits_other"]
        assert ProtocolMessageTypes.request_block not in rl_2["rate_limits_tx"]

        comps = compose_rate_limits(rl_1, rl_2)
        # v2 limits are used if present
        assert ProtocolMessageTypes.respond_children not in comps["rate_limits_other"]
        assert ProtocolMessageTypes.respond_children in comps["rate_limits_tx"]

        # Otherwise, fall back to v1
        assert ProtocolMessageTypes.request_block in rl_1["rate_limits_other"]
        assert ProtocolMessageTypes.request_block not in rl_1["rate_limits_tx"]
