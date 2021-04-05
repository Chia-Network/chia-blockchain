import asyncio

import pytest

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import make_msg
from chia.server.rate_limits import RateLimiter
from tests.setup_nodes import test_constants


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


constants = test_constants


class TestRateLimits:
    @pytest.mark.asyncio
    async def test_too_many_messages(self):
        # Too many messages
        r = RateLimiter()
        new_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 40))
        for i in range(3000):
            assert r.process_msg_and_check(new_tx_message)

        saw_disconnect = False
        for i in range(3000):
            response = r.process_msg_and_check(new_tx_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Non-tx message
        r = RateLimiter()
        new_peak_message = make_msg(ProtocolMessageTypes.new_peak, bytes([1] * 40))
        for i in range(20):
            assert r.process_msg_and_check(new_peak_message)

        saw_disconnect = False
        for i in range(200):
            response = r.process_msg_and_check(new_peak_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

    @pytest.mark.asyncio
    async def test_large_message(self):
        # Large tx
        small_tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
        large_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 3 * 1024 * 1024))

        r = RateLimiter()
        assert r.process_msg_and_check(small_tx_message)
        assert r.process_msg_and_check(small_tx_message)
        assert not r.process_msg_and_check(large_tx_message)

        small_vdf_message = make_msg(ProtocolMessageTypes.respond_signage_point, bytes([1] * 5 * 1024))
        large_vdf_message = make_msg(ProtocolMessageTypes.respond_signage_point, bytes([1] * 600 * 1024))
        r = RateLimiter()
        assert r.process_msg_and_check(small_vdf_message)
        assert r.process_msg_and_check(small_vdf_message)
        assert not r.process_msg_and_check(large_vdf_message)

    @pytest.mark.asyncio
    async def test_too_much_data(self):
        # Too much data
        r = RateLimiter()
        tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
        for i in range(10):
            assert r.process_msg_and_check(tx_message)

        saw_disconnect = False
        for i in range(300):
            response = r.process_msg_and_check(tx_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        r = RateLimiter()
        block_message = make_msg(ProtocolMessageTypes.respond_block, bytes([1] * 1024 * 1024))
        for i in range(10):
            assert r.process_msg_and_check(block_message)

        saw_disconnect = False
        for i in range(40):
            response = r.process_msg_and_check(block_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

    @pytest.mark.asyncio
    async def test_non_tx_aggregate_limits(self):
        # Frequency limits
        r = RateLimiter()
        message_1 = make_msg(ProtocolMessageTypes.request_additions, bytes([1] * 5 * 1024))
        message_2 = make_msg(ProtocolMessageTypes.request_removals, bytes([1] * 1024))
        message_3 = make_msg(ProtocolMessageTypes.respond_additions, bytes([1] * 1024))

        for i in range(450):
            assert r.process_msg_and_check(message_1)
        for i in range(450):
            assert r.process_msg_and_check(message_2)

        saw_disconnect = False
        for i in range(450):
            response = r.process_msg_and_check(message_3)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Size limits
        r = RateLimiter()
        message_4 = make_msg(ProtocolMessageTypes.respond_proof_of_weight, bytes([1] * 49 * 1024 * 1024))
        message_5 = make_msg(ProtocolMessageTypes.respond_blocks, bytes([1] * 49 * 1024 * 1024))

        for i in range(2):
            assert r.process_msg_and_check(message_4)

        saw_disconnect = False
        for i in range(2):
            response = r.process_msg_and_check(message_5)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

    @pytest.mark.asyncio
    async def test_periodic_reset(self):
        r = RateLimiter(5)
        tx_message = make_msg(ProtocolMessageTypes.respond_transaction, bytes([1] * 500 * 1024))
        for i in range(10):
            assert r.process_msg_and_check(tx_message)

        saw_disconnect = False
        for i in range(300):
            response = r.process_msg_and_check(tx_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect
        assert not r.process_msg_and_check(tx_message)
        await asyncio.sleep(6)
        assert r.process_msg_and_check(tx_message)

        # Counts reset also
        r = RateLimiter(5)
        new_tx_message = make_msg(ProtocolMessageTypes.new_transaction, bytes([1] * 40))
        for i in range(3000):
            assert r.process_msg_and_check(new_tx_message)

        saw_disconnect = False
        for i in range(3000):
            response = r.process_msg_and_check(new_tx_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect
        assert not r.process_msg_and_check(new_tx_message)
        await asyncio.sleep(6)
        assert r.process_msg_and_check(new_tx_message)

    @pytest.mark.asyncio
    async def test_percentage_limits(self):
        r = RateLimiter(60, 40)
        new_peak_message = make_msg(ProtocolMessageTypes.new_peak, bytes([1] * 40))
        for i in range(50):
            assert r.process_msg_and_check(new_peak_message)

        saw_disconnect = False
        for i in range(50):
            response = r.process_msg_and_check(new_peak_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        r = RateLimiter(60, 40)
        block_message = make_msg(ProtocolMessageTypes.respond_block, bytes([1] * 1024 * 1024))
        for i in range(5):
            assert r.process_msg_and_check(block_message)

        saw_disconnect = False
        for i in range(5):
            response = r.process_msg_and_check(block_message)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Aggregate percentage limit count
        r = RateLimiter(60, 40)
        message_1 = make_msg(ProtocolMessageTypes.request_additions, bytes([1] * 5 * 1024))
        message_2 = make_msg(ProtocolMessageTypes.request_removals, bytes([1] * 1024))
        message_3 = make_msg(ProtocolMessageTypes.respond_additions, bytes([1] * 1024))

        for i in range(180):
            assert r.process_msg_and_check(message_1)
        for i in range(180):
            assert r.process_msg_and_check(message_2)

        saw_disconnect = False
        for i in range(100):
            response = r.process_msg_and_check(message_3)
            if not response:
                saw_disconnect = True
        assert saw_disconnect

        # Aggregate percentage limit max total size
        r = RateLimiter(60, 40)
        message_4 = make_msg(ProtocolMessageTypes.respond_proof_of_weight, bytes([1] * 18 * 1024 * 1024))
        message_5 = make_msg(ProtocolMessageTypes.respond_blocks, bytes([1] * 24 * 1024 * 1024))

        for i in range(2):
            assert r.process_msg_and_check(message_4)

        saw_disconnect = False
        for i in range(2):
            response = r.process_msg_and_check(message_5)
            if not response:
                saw_disconnect = True
        assert saw_disconnect
