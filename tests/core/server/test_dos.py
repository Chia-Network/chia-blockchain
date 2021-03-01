# flake8: noqa: F811, F401
import asyncio
import dataclasses

import pytest
import random
import time
import logging
from typing import Dict
from secrets import token_bytes

from aiohttp import ClientTimeout, ClientSession, WSMessage, WSMsgType, WSCloseCode, ServerDisconnectedError
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

from src.consensus.pot_iterations import is_overflow_block
from src.full_node.full_node_api import FullNodeAPI
from src.protocols import full_node_protocol as fnp
from src.protocols.protocol_message_types import ProtocolMessageTypes
from src.server.server import ssl_context_for_client
from src.server.ws_connection import WSChiaConnection
from src.types.blockchain_format.program import SerializedProgram
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.types.peer_info import TimestampedPeerInfo, PeerInfo
from src.server.address_manager import AddressManager
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.util.block_tools import get_signage_point
from src.util.errors import Err
from src.util.hash import std_hash
from src.util.ints import uint16, uint32, uint64, uint8
from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.util.wallet_tools import WalletTool
from tests.connection_utils import add_dummy_connection, connect_and_get_peer
from tests.core.full_node.test_coin_store import get_future_reward_coins
from tests.setup_nodes import test_constants, bt, self_hostname, setup_simulators_and_wallets
from src.util.clvm import int_to_bytes
from tests.core.full_node.test_full_sync import node_height_at_least
from tests.time_out_assert import (
    time_out_assert,
    time_out_assert_custom_interval,
    time_out_messages,
)

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
        assert ws.closed
        try:
            await session.ws_connect(
                url, autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=100 * 1024 * 1024
            )
            assert False
        except ServerDisconnectedError:
            pass
        await session.close()
