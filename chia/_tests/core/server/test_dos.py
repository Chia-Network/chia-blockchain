# flake8: noqa: F811, F401
from __future__ import annotations

import asyncio
import logging

import pytest
from aiohttp import ClientSession, ClientTimeout, ServerDisconnectedError, WSCloseCode, WSMessage, WSMsgType

from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Handshake
from chia.server.outbound_message import Message, make_msg
from chia.server.rate_limits import RateLimiter
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo
from chia.util.errors import Err
from chia.util.ints import uint64

log = logging.getLogger(__name__)


async def get_block_path(full_node: FullNodeAPI):
    blocks_list = [await full_node.full_node.blockchain.get_full_peak()]
    assert blocks_list[0] is not None
    while blocks_list[0].height != 0:
        b = await full_node.full_node.block_store.get_full_block(blocks_list[0].prev_header_hash)
        assert b is not None
        blocks_list.insert(0, b)
    return blocks_list


class FakeRateLimiter:
    def process_msg_and_check(self, msg, capa, capb):
        return True


class TestDos:
    @pytest.mark.anyio
    async def test_large_message_disconnect_and_ban(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, _ = setup_two_nodes_fixture
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        # Use the server_2 ssl information to connect to server_1, and send a huge message
        timeout = ClientTimeout(total=10)
        session = ClientSession(timeout=timeout)
        url = f"wss://{self_hostname}:{server_1._port}/ws"

        ssl_context = server_2.ssl_client_context
        ws = await session.ws_connect(
            url, autoclose=True, autoping=True, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
        )
        assert not ws.closed
        await ws.close()
        assert ws.closed

        ws = await session.ws_connect(
            url, autoclose=True, autoping=True, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
        )
        assert not ws.closed

        large_msg: bytes = bytes([0] * (60 * 1024 * 1024))
        await ws.send_bytes(large_msg)

        response: WSMessage = await ws.receive()
        print(response)
        assert response.type == WSMsgType.CLOSE
        assert response.data == WSCloseCode.MESSAGE_TOO_BIG
        await ws.close()

        # Now test that the ban is active
        await asyncio.sleep(5)
        assert ws.closed
        try:
            ws = await session.ws_connect(
                url, autoclose=True, autoping=True, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
            )
            response: WSMessage = await ws.receive()
            assert response.type == WSMsgType.CLOSE
        except ServerDisconnectedError:
            pass
        await session.close()

    @pytest.mark.anyio
    async def test_bad_handshake_and_ban(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, _ = setup_two_nodes_fixture
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        server_1.invalid_protocol_ban_seconds = 10
        # Use the server_2 ssl information to connect to server_1, and send a huge message
        timeout = ClientTimeout(total=10)
        session = ClientSession(timeout=timeout)
        url = f"wss://{self_hostname}:{server_1._port}/ws"

        ssl_context = server_2.ssl_client_context
        ws = await session.ws_connect(
            url, autoclose=True, autoping=True, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
        )
        await ws.send_bytes(bytes([1] * 1024))

        response: WSMessage = await ws.receive()
        print(response)
        assert response.type == WSMsgType.CLOSE
        assert response.data == WSCloseCode.PROTOCOL_ERROR
        await ws.close()

        # Now test that the ban is active
        await asyncio.sleep(5)
        assert ws.closed
        try:
            ws = await session.ws_connect(
                url, autoclose=True, autoping=True, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
            )
            response: WSMessage = await ws.receive()
            assert response.type == WSMsgType.CLOSE
        except ServerDisconnectedError:
            pass
        await asyncio.sleep(6)

        # Ban expired
        await session.ws_connect(url, autoclose=True, autoping=True, ssl=ssl_context, max_msg_size=100 * 1024 * 1024)

        await session.close()

    @pytest.mark.anyio
    async def test_invalid_protocol_handshake(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, _ = setup_two_nodes_fixture
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        server_1.invalid_protocol_ban_seconds = 10
        # Use the server_2 ssl information to connect to server_1
        timeout = ClientTimeout(total=10)
        session = ClientSession(timeout=timeout)
        url = f"wss://{self_hostname}:{server_1._port}/ws"

        ssl_context = server_2.ssl_client_context
        ws = await session.ws_connect(
            url, autoclose=True, autoping=True, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
        )

        # Construct an otherwise valid handshake message
        handshake: Handshake = Handshake("test", "0.0.32", "1.0.0.0", 3456, 1, [(1, "1")])
        outbound_handshake: Message = Message(2, None, bytes(handshake))  # 2 is an invalid ProtocolType
        await ws.send_bytes(bytes(outbound_handshake))

        response: WSMessage = await ws.receive()
        print(response)
        assert response.type == WSMsgType.CLOSE
        assert response.data == WSCloseCode.PROTOCOL_ERROR
        assert response.extra == str(int(Err.INVALID_HANDSHAKE.value))  # We want INVALID_HANDSHAKE and not UNKNOWN
        await ws.close()
        await session.close()
        await asyncio.sleep(1)  # give some time for cleanup to work

    @pytest.mark.anyio
    async def test_spam_tx(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, _ = setup_two_nodes_fixture
        full_node_1, full_node_2 = nodes
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)

        assert len(server_1.all_connections) == 1

        ws_con: WSChiaConnection = list(server_1.all_connections.values())[0]
        ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

        ws_con.peer_info = PeerInfo("1.2.3.4", ws_con.peer_info.port)
        ws_con_2.peer_info = PeerInfo("1.2.3.4", ws_con_2.peer_info.port)

        new_tx_message = make_msg(
            ProtocolMessageTypes.new_transaction,
            full_node_protocol.NewTransaction(bytes([9] * 32), uint64(0), uint64(0)),
        )
        for i in range(4000):
            await ws_con._send_message(new_tx_message)

        await asyncio.sleep(1)
        assert not ws_con.closed

        # Tests outbound rate limiting, we will not send too much data
        for i in range(2000):
            await ws_con._send_message(new_tx_message)

        await asyncio.sleep(1)
        assert not ws_con.closed

        # Remove outbound rate limiter to test inbound limits
        ws_con.outbound_rate_limiter = RateLimiter(incoming=True, percentage_of_limit=10000)

        with pytest.raises(ConnectionResetError):
            for i in range(6000):
                await ws_con._send_message(new_tx_message)
                await asyncio.sleep(0)
        await asyncio.sleep(1)

        def is_closed():
            return ws_con.closed

        await time_out_assert(15, is_closed)

        assert ws_con.closed

        def is_banned():
            return "1.2.3.4" in server_2.banned_peers

        await time_out_assert(15, is_banned)

    @pytest.mark.anyio
    async def test_spam_message_non_tx(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, _ = setup_two_nodes_fixture
        full_node_1, full_node_2 = nodes
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)

        assert len(server_1.all_connections) == 1

        ws_con: WSChiaConnection = list(server_1.all_connections.values())[0]
        ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

        ws_con.peer_info = PeerInfo("1.2.3.4", ws_con.peer_info.port)
        ws_con_2.peer_info = PeerInfo("1.2.3.4", ws_con_2.peer_info.port)

        def is_closed():
            return ws_con.closed

        new_message = make_msg(
            ProtocolMessageTypes.request_mempool_transactions,
            full_node_protocol.RequestMempoolTransactions(bytes([])),
        )
        for i in range(2):
            await ws_con._send_message(new_message)
        await asyncio.sleep(1)
        assert not ws_con.closed

        # Tests outbound rate limiting, we will not send too much data
        for i in range(10):
            await ws_con._send_message(new_message)

        await asyncio.sleep(1)
        assert not ws_con.closed

        # Remove outbound rate limiter to test inbound limits
        ws_con.outbound_rate_limiter = RateLimiter(incoming=True, percentage_of_limit=10000)

        for i in range(6):
            await ws_con._send_message(new_message)
        await time_out_assert(15, is_closed)

        # Banned
        def is_banned():
            return "1.2.3.4" in server_2.banned_peers

        await time_out_assert(15, is_banned)

    @pytest.mark.anyio
    async def test_spam_message_too_large(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, _ = setup_two_nodes_fixture
        full_node_1, full_node_2 = nodes
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), full_node_2.full_node.on_connect)

        assert len(server_1.all_connections) == 1

        ws_con: WSChiaConnection = list(server_1.all_connections.values())[0]
        ws_con_2: WSChiaConnection = list(server_2.all_connections.values())[0]

        ws_con.peer_info = PeerInfo("1.2.3.4", ws_con.peer_info.port)
        ws_con_2.peer_info = PeerInfo("1.2.3.4", ws_con_2.peer_info.port)

        def is_closed():
            return ws_con.closed

        new_message = make_msg(
            ProtocolMessageTypes.request_mempool_transactions,
            full_node_protocol.RequestMempoolTransactions(bytes([0] * 5 * 1024 * 1024)),
        )
        # Tests outbound rate limiting, we will not send big messages
        await ws_con._send_message(new_message)

        await asyncio.sleep(1)
        assert not ws_con.closed

        # Remove outbound rate limiter to test inbound limits
        ws_con.outbound_rate_limiter = FakeRateLimiter()

        await ws_con._send_message(new_message)
        await time_out_assert(15, is_closed)

        # Banned
        def is_banned():
            return "1.2.3.4" in server_2.banned_peers

        await time_out_assert(15, is_banned)
