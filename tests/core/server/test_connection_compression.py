# flake8: noqa: F811, F401
from __future__ import annotations

import asyncio
from typing import Any, List, Optional

import pytest
import zstd

from chia.protocols import full_node_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.server.outbound_message import Message, make_msg
from chia.server.server import max_message_size
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo
from chia.util.errors import ProtocolError
from chia.util.ints import uint8, uint16, uint32
from chia.util.zstandard import get_decompressed_size


def set_to_wellknown_state(servers: List[Any]) -> None:

    for s in servers:
        # set these to a known condition, disregarding values in initial-config.yaml
        s.config["cx_decompressing_messages_supported"] = False
        s.config["cx_sending_compressed_messages_enabled"] = False
        s.config["cx_compress_if_at_least_size"] = 8 * 1024
        # the rest are set in the constructor for ChiaServer, undo it if the config had "True"
        s.sending_compressed_messages_enabled = False
        s.compress_if_at_least_size = 8 * 1024
        if (uint16(Capability.CAN_DECOMPRESS_MESSAGES.value), "1") in s._local_capabilities_for_handshake:
            s._local_capabilities_for_handshake.remove((uint16(Capability.CAN_DECOMPRESS_MESSAGES.value), "1"))


class TestConnectionCompression:
    @pytest.mark.asyncio
    async def test_baseline(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

        # neither node can compress nor decompress

        nodes, _, _ = setup_two_nodes_fixture
        node_1, node_2 = nodes
        full_node_1 = node_1.full_node
        full_node_2 = node_2.full_node
        server_1 = full_node_1.server
        server_2 = full_node_2.server

        set_to_wellknown_state([server_1, server_2])

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        assert len(server_1.all_connections) == 1
        assert len(server_2.all_connections) == 1

        ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
        ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

        assert ws_con_1.sending_compressed_enabled == False
        assert ws_con_2.sending_compressed_enabled == False

        assert Capability.CAN_DECOMPRESS_MESSAGES not in ws_con_1.local_capabilities
        assert Capability.CAN_DECOMPRESS_MESSAGES not in ws_con_2.local_capabilities

        # Test full-circle communication

        res = await node_2.request_block(
            full_node_protocol.RequestBlock(height=uint32(1), include_transaction_block=False)
        )
        assert res.type == ProtocolMessageTypes.reject_block.value  # haven't added any blocks yet

        # Test on-the-wire bytes

        new_message = make_msg(
            ProtocolMessageTypes.request_block,
            full_node_protocol.RequestBlock(height=uint32(1), include_transaction_block=False),
        )
        await ws_con_1._send_message(new_message)

        while not ws_con_2.closed:
            message: Optional[Message] = await ws_con_2._read_one_message()
            if message is not None:
                assert message.type == ProtocolMessageTypes.request_block.value
                assert message.data == bytes([0, 0, 0, 1, 0])
                break
            else:
                continue

        # Test sending a compressed message
        # The receiver should not decompress it, instead try to ban us for protocol violation

        new_message = make_msg(
            ProtocolMessageTypes.wrapped_compressed,
            full_node_protocol.WrappedCompressed(
                uint8(ProtocolMessageTypes.request_block.value),
                zstd.compress(bytes(full_node_protocol.RequestBlock(height=uint32(1), include_transaction_block=False))),
            ),
        )
        await ws_con_1._send_message(new_message)

        # If not automatic decompression, the message doesn't reach the receiver

        with pytest.raises(ProtocolError):
            message = await ws_con_2._read_one_message()

        server_2.close_all()
        await server_2.await_closed()
        await asyncio.sleep(0.3)

    @pytest.mark.asyncio
    async def test_compressing(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

        nodes, _, _ = setup_two_nodes_fixture
        node_1, node_2 = nodes
        full_node_1 = node_1.full_node
        full_node_2 = node_2.full_node
        server_1 = full_node_1.server
        server_2 = full_node_2.server

        set_to_wellknown_state([server_1, server_2])

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        assert len(server_1.all_connections) == 1
        assert len(server_2.all_connections) == 1

        ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
        ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

        # make node 1 capable of sending compressed
        # and pretend the peer can decompress
        ws_con_1.sending_compressed_enabled = True
        ws_con_1.peer_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

        # Small message (smaller than 8*1024 bytes): doesn't compress

        small_message = make_msg(
            ProtocolMessageTypes.request_block,
            full_node_protocol.RequestBlock(height=uint32(1), include_transaction_block=False),
        )
        msg = ws_con_1._potentially_compress(small_message)

        assert msg == small_message

        # Big message (larger than 8*1024 bytes): compresses

        big_message = make_msg(
            ProtocolMessageTypes.request_mempool_transactions,
            full_node_protocol.RequestMempoolTransactions(bytes([0] * 20 * 1024)),
        )
        assert len(big_message.data) >= 8 * 1024
        msg = ws_con_1._potentially_compress(big_message)

        assert msg != big_message
        assert msg.type == ProtocolMessageTypes.wrapped_compressed.value
        wrappedcompressed = full_node_protocol.WrappedCompressed.from_bytes(msg.data)
        assert wrappedcompressed.inner_type == ProtocolMessageTypes.request_mempool_transactions.value
        assert get_decompressed_size(wrappedcompressed.data) == len(big_message.data)

        assert wrappedcompressed.data == bytes(
            [
                0x28,
                0xB5,
                0x2F,
                0xFD,  # magic bytes
                0x60,
                0x04,
                0x4F,
                0x5D,
                0x00,
                0x00,
                0x20,
                0x00,
                0x00,
                0x50,
                0x00,
                0x01,
                0x00,
                0xFD,
                0xCF,
                0x0E,
                0x88,
            ]
        )
        # by using specific bytes we get to know if zstd changes format or something

        # trying to compress an already compressed message doesn't do it,
        # ie. "_potentially_compress" returns the compressed message without changes.

        ws_con_1.compress_if_at_least_size = len(bytes(msg.data)) - 1
        again_msg = ws_con_1._potentially_compress(msg)
        assert again_msg == msg
        assert again_msg.type == msg.type
        assert again_msg.data == msg.data

        server_2.close_all()
        await server_2.await_closed()
        await asyncio.sleep(0.3)

    @pytest.mark.asyncio
    async def test_decompress(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

        nodes, _, _ = setup_two_nodes_fixture
        node_1, node_2 = nodes
        full_node_1 = node_1.full_node
        full_node_2 = node_2.full_node
        server_1 = full_node_1.server
        server_2 = full_node_2.server

        set_to_wellknown_state([server_1, server_2])

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        assert len(server_1.all_connections) == 1
        assert len(server_2.all_connections) == 1

        ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
        ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

        # The first parts for these tests are when decompression is not enabled, but received anyway

        assert Capability.CAN_DECOMPRESS_MESSAGES not in ws_con_1.local_capabilities

        compressed_msg = make_msg(
            ProtocolMessageTypes.wrapped_compressed,
            full_node_protocol.WrappedCompressed(uint8(ProtocolMessageTypes.respond_blocks.value), zstd.compress(bytes([0] * 1000))),
        )

        with pytest.raises(ProtocolError):
            decompressed_msg = await ws_con_1._decompress_message(compressed_msg)

        compressed_msg = make_msg(ProtocolMessageTypes.wrapped_compressed, bytes([]))

        with pytest.raises(ProtocolError):
            decompressed_msg = await ws_con_1._decompress_message(compressed_msg)

        # The rest of these tests are when decompression is enabled

        ws_con_1.local_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)
        assert Capability.CAN_DECOMPRESS_MESSAGES in ws_con_1.local_capabilities

        compressed_msg = make_msg(
            ProtocolMessageTypes.wrapped_compressed,
            full_node_protocol.WrappedCompressed(uint8(ProtocolMessageTypes.respond_blocks.value), zstd.compress(bytes([0] * 1000))),
        )

        decompressed_msg = await ws_con_1._decompress_message(compressed_msg)
        assert decompressed_msg is not None
        assert decompressed_msg.type == ProtocolMessageTypes.respond_blocks.value
        assert decompressed_msg.data == bytes([0] * 1000)

        compressed_msg = make_msg(ProtocolMessageTypes.wrapped_compressed, bytes([]))

        with pytest.raises(ProtocolError):
            decompressed_msg = await ws_con_1._decompress_message(compressed_msg)

        # Making sure an invalid ProtocolMessageTypes doesn't trip up the logging in _decompress_message

        compressed_msg = make_msg(
            ProtocolMessageTypes.wrapped_compressed,
            full_node_protocol.WrappedCompressed(uint8(0), zstd.compress(bytes([0] * 1000)))
        )

        with pytest.raises(ProtocolError):
            decompressed_msg = await ws_con_1._decompress_message(compressed_msg)

        server_2.close_all()
        await server_2.await_closed()
        await asyncio.sleep(0.3)

    class TestsNodesCapabilitiesDiffer:

        # node_1 can compress, node_2 can decompress

        @pytest.mark.asyncio
        async def test_node1_sends_small_uncompressed(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

            nodes, _, _ = setup_two_nodes_fixture
            node_1, node_2 = nodes
            full_node_1 = node_1.full_node
            full_node_2 = node_2.full_node
            server_1 = full_node_1.server
            server_2 = full_node_2.server

            set_to_wellknown_state([server_1, server_2])

            await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

            assert len(server_1.all_connections) == 1
            assert len(server_2.all_connections) == 1

            ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
            ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

            # make node 1 capable of sending compressed
            # and pretend the peer can decompress (the peer itself isn't changed because
            # that would do the decompression before we get the message)
            ws_con_1.sending_compressed_enabled = True
            ws_con_1.peer_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # do not make node 2 capable of decompression
            # that would do the decompression before we get the message
            # instead, make sure it doesn't do decompression
            assert Capability.CAN_DECOMPRESS_MESSAGES not in ws_con_2.local_capabilities

            new_message = make_msg(
                ProtocolMessageTypes.request_mempool_transactions,
                full_node_protocol.RequestMempoolTransactions(bytes([0] * 5 * 1024)),
            )
            await ws_con_1._send_message(new_message)

            while not ws_con_2.closed:
                message = await ws_con_2._read_one_message()
                if message is not None:
                    assert message.type == ProtocolMessageTypes.request_mempool_transactions.value
                    assert message.data == uint32(5 * 1024).to_bytes(length=4, byteorder="big", signed=False) + bytes(
                        [0] * 5 * 1024
                    )
                    break
                else:
                    continue

            server_2.close_all()
            await server_2.await_closed()
            await asyncio.sleep(0.3)

        @pytest.mark.asyncio
        async def test_node1_sends_big_compressed(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

            nodes, _, _ = setup_two_nodes_fixture
            node_1, node_2 = nodes
            full_node_1 = node_1.full_node
            full_node_2 = node_2.full_node
            server_1 = full_node_1.server
            server_2 = full_node_2.server

            set_to_wellknown_state([server_1, server_2])

            await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

            assert len(server_1.all_connections) == 1
            assert len(server_2.all_connections) == 1

            ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
            ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

            # make node 1 capable of sending compressed
            # and pretend the peer can decompress
            ws_con_1.sending_compressed_enabled = True
            ws_con_1.peer_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # do not make node 2 capable of decompression
            # that would do the decompression before we get the message
            # instead, make sure it doesn't do decompression
            assert Capability.CAN_DECOMPRESS_MESSAGES not in ws_con_2.local_capabilities

            new_message = make_msg(
                ProtocolMessageTypes.request_mempool_transactions,
                full_node_protocol.RequestMempoolTransactions(bytes([0] * 20 * 1024)),
            )
            await ws_con_1._send_message(new_message)

            with pytest.raises(ProtocolError):
                message = await ws_con_2._read_one_message()

            server_2.close_all()
            await server_2.await_closed()
            await asyncio.sleep(0.3)

        @pytest.mark.asyncio
        async def test_node2_sends_uncompressed_regardless(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

            nodes, _, _ = setup_two_nodes_fixture
            node_1, node_2 = nodes
            full_node_1 = node_1.full_node
            full_node_2 = node_2.full_node
            server_1 = full_node_1.server
            server_2 = full_node_2.server

            set_to_wellknown_state([server_1, server_2])

            await server_1.start_client(PeerInfo(self_hostname, uint16(server_2._port)), None)

            assert len(server_1.all_connections) == 1
            assert len(server_2.all_connections) == 1

            ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
            ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

            # node 2 cannot send compressed
            # (even if it knows the peer can decompress)
            ws_con_2.sending_compressed_enabled = False
            ws_con_2.peer_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # making sure it doesn't decompress behind our back
            assert Capability.CAN_DECOMPRESS_MESSAGES not in ws_con_1.local_capabilities

            # testing small message

            small_message = make_msg(
                ProtocolMessageTypes.request_block,
                full_node_protocol.RequestBlock(height=uint32(1), include_transaction_block=False),
            )
            await ws_con_2._send_message(small_message)

            while not ws_con_1.closed:
                message: Optional[Message] = await ws_con_1._read_one_message()
                if message is not None:
                    assert message.type == ProtocolMessageTypes.request_block.value
                    assert message.data == bytes([0, 0, 0, 1, 0])
                    break
                else:
                    continue

            # now testing big message (20 KiB)

            big_message = make_msg(
                ProtocolMessageTypes.request_mempool_transactions,
                full_node_protocol.RequestMempoolTransactions(bytes([0] * 20 * 1024)),
            )
            await ws_con_2._send_message(big_message)

            while not ws_con_1.closed:
                message = await ws_con_1._read_one_message()
                if message is not None:
                    assert message.type == ProtocolMessageTypes.request_mempool_transactions.value
                    assert message.data == uint32(20 * 1024).to_bytes(length=4, byteorder="big", signed=False) + bytes(
                        [0] * 20 * 1024
                    )
                    # not a compressed message on the wire
                    break
                else:
                    continue

            server_1.close_all()
            await server_1.await_closed()
            await asyncio.sleep(0.3)

    class TestsMalformedMessages:
        @pytest.mark.asyncio
        async def test_wrapped_compressed_but_0_data_bytes(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

            nodes, _, _ = setup_two_nodes_fixture
            node_1, node_2 = nodes
            full_node_1 = node_1.full_node
            full_node_2 = node_2.full_node
            server_1 = full_node_1.server
            server_2 = full_node_2.server

            set_to_wellknown_state([server_1, server_2])

            await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

            assert len(server_1.all_connections) == 1
            assert len(server_2.all_connections) == 1

            ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
            ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

            # make node 1 capable of sending compressed
            # and pretend the peer can decompress
            ws_con_1.sending_compressed_enabled = True
            ws_con_1.peer_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # make node 2 actually capable of decompression
            ws_con_2.local_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # Mal-formed
            # No inner-type, and no data
            malformed_message = make_msg(ProtocolMessageTypes.wrapped_compressed, bytes([]))
            await ws_con_1._send_message(malformed_message)

            # Try to read the message - it should be a protocol violation
            with pytest.raises(ProtocolError):
                message = await ws_con_2._read_one_message()

            server_2.close_all()
            await server_2.await_closed()
            await asyncio.sleep(0.3)

        @pytest.mark.asyncio
        async def test_wrapped_compressed_but_2_data_bytes(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

            nodes, _, _ = setup_two_nodes_fixture
            node_1, node_2 = nodes
            full_node_1 = node_1.full_node
            full_node_2 = node_2.full_node
            server_1 = full_node_1.server
            server_2 = full_node_2.server

            set_to_wellknown_state([server_1, server_2])

            await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

            assert len(server_1.all_connections) == 1
            assert len(server_2.all_connections) == 1

            ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
            ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

            # make node 1 capable of sending compressed
            # and pretend the peer can decompress
            ws_con_1.sending_compressed_enabled = True
            ws_con_1.peer_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # make node 2 actually capable of decompression
            ws_con_2.local_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # Mal-formed
            # Only inner-type, and 2 bytes for the zstd magic bytes (should be 4) as data
            malformed_message = make_msg(
                ProtocolMessageTypes.wrapped_compressed,
                full_node_protocol.WrappedCompressed(
                    uint8(ProtocolMessageTypes.request_mempool_transactions.value),
                    bytes(
                        [
                            0x28,
                            0xB5,  # not enough of the zstd magic bytes (in little-endian)
                        ]
                    )
                ),
            )
            await ws_con_1._send_message(malformed_message)

            # Try to read the message - it should be a protocol violation
            with pytest.raises(ProtocolError):
                message = await ws_con_2._read_one_message()

            server_2.close_all()
            await server_2.await_closed()
            await asyncio.sleep(0.3)

        @pytest.mark.asyncio
        async def test_wrapped_compressed_but_too_big_uncompressed(self, setup_two_nodes_fixture: Any, self_hostname: str) -> None:

            nodes, _, _ = setup_two_nodes_fixture
            node_1, node_2 = nodes
            full_node_1 = node_1.full_node
            full_node_2 = node_2.full_node
            server_1 = full_node_1.server
            server_2 = full_node_2.server

            set_to_wellknown_state([server_1, server_2])

            await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

            assert len(server_1.all_connections) == 1
            assert len(server_2.all_connections) == 1

            ws_con_1: WSChiaConnection = list(server_1.all_connections.values())[0]
            ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

            # make node 1 capable of sending compressed
            # and pretend the peer can decompress
            ws_con_1.sending_compressed_enabled = True
            ws_con_1.peer_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # make node 2 actually capable of decompression
            ws_con_2.local_capabilities.append(Capability.CAN_DECOMPRESS_MESSAGES)

            # create a message that uncompressed is too big, but compressed is ok
            wrappedcompressed = full_node_protocol.WrappedCompressed(
                uint8(ProtocolMessageTypes.request_mempool_transactions.value),
                zstd.compress(
                    bytes(full_node_protocol.RequestMempoolTransactions(bytes([0] * (max_message_size + 10)))),
                ),
            )
            too_big_message = make_msg(ProtocolMessageTypes.wrapped_compressed, wrappedcompressed)

            # the message is not too big to send
            assert len(bytes(too_big_message)) < max_message_size

            # but the uncompressed size is too big
            assert get_decompressed_size(wrappedcompressed.data) > max_message_size

            # sending this specially crafted message succeeds (but the peer will ban us)
            await ws_con_1._send_message(too_big_message)

            # Try to read the message - it should be a protocol violation
            with pytest.raises(ProtocolError):
                message = await ws_con_2._read_one_message()

            server_2.close_all()
            await server_2.await_closed()
            await asyncio.sleep(0.3)

        def test_get_decompressed_size(self) -> None:

            # making sure get_decompressed_size() returns the correct size

            # kilobyte ranges
            for i in range(1, 1024):
                sz = i * 1024
                uncompressed = bytes([0] * sz)
                compressed = zstd.compress(uncompressed)
                assert zstd.decompress(compressed) == uncompressed
                assert sz == get_decompressed_size(compressed)

            # megabyte ranges
            for i in range(40, 55):
                sz = i * 1024 * 1024
                uncompressed = bytes([0] * sz)
                compressed = zstd.compress(uncompressed)
                assert zstd.decompress(compressed) == uncompressed
                assert sz == get_decompressed_size(compressed)

            # (the fact that anything larger than 50 MB is too large is tested elsewhere)
