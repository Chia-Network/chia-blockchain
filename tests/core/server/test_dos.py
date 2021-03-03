# flake8: noqa: F811, F401
import asyncio

import pytest
import logging

from aiohttp import ClientTimeout, ClientSession, WSMessage, WSMsgType, WSCloseCode, ServerDisconnectedError

from src.full_node.full_node_api import FullNodeAPI
from src.server.server import ssl_context_for_client
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets

log = logging.getLogger(__name__)


async def get_block_path(full_node: FullNodeAPI):
    blocks_list = [await full_node.full_node.blockchain.get_full_peak()]
    assert blocks_list[0] is not None
    while blocks_list[0].height != 0:
        b = await full_node.full_node.block_store.get_full_block(blocks_list[0].prev_header_hash)
        assert b is not None
        blocks_list.insert(0, b)
    return blocks_list


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="function")
async def setup_two_nodes():
    async for _ in setup_simulators_and_wallets(2, 0, {}, starting_port=60000):
        yield _


class TestDos:
    @pytest.mark.asyncio
    @pytest.mark.skip("Not working in CI")
    async def test_large_message_disconnect_and_ban(self, setup_two_nodes):
        nodes, _ = setup_two_nodes
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        # Use the server_2 ssl information to connect to server_1, and send a huge message
        timeout = ClientTimeout(total=10)
        session = ClientSession(timeout=timeout)
        url = f"wss://{self_hostname}:{server_1._port}/ws"

        ssl_context = ssl_context_for_client(
            server_2.chia_ca_crt_path, server_2.chia_ca_key_path, server_2.p2p_crt_path, server_2.p2p_key_path
        )
        ws = await session.ws_connect(
            url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
        )
        assert not ws.closed
        await ws.close()
        assert ws.closed

        ws = await session.ws_connect(
            url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
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
        await asyncio.sleep(2)
        assert ws.closed
        try:
            await session.ws_connect(
                url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
            )
            assert False
        except ServerDisconnectedError:
            pass
        await session.close()

    @pytest.mark.asyncio
    @pytest.mark.skip("Not working in CI")
    async def test_bad_handshake_and_ban(self, setup_two_nodes):
        nodes, _ = setup_two_nodes
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server

        server_1.invalid_protocol_ban_seconds = 3
        # Use the server_2 ssl information to connect to server_1, and send a huge message
        timeout = ClientTimeout(total=10)
        session = ClientSession(timeout=timeout)
        url = f"wss://{self_hostname}:{server_1._port}/ws"

        ssl_context = ssl_context_for_client(
            server_2.chia_ca_crt_path, server_2.chia_ca_key_path, server_2.p2p_crt_path, server_2.p2p_key_path
        )
        ws = await session.ws_connect(
            url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
        )
        await ws.send_bytes(bytes([1] * 1024))

        response: WSMessage = await ws.receive()
        print(response)
        assert response.type == WSMsgType.CLOSE
        assert response.data == WSCloseCode.PROTOCOL_ERROR
        await ws.close()

        # Now test that the ban is active
        assert ws.closed
        try:
            await session.ws_connect(
                url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
            )
            assert False
        except ServerDisconnectedError:
            pass
        await asyncio.sleep(4)

        # Ban expired
        await session.ws_connect(
            url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
        )

        await session.close()
