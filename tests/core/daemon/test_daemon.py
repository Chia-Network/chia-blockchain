import asyncio
import json

import aiohttp
import pytest
from chia.server.outbound_message import NodeType
from chia.server.server import ssl_context_for_server
from chia.types.peer_info import PeerInfo
from tests.block_tools import BlockTools
from chia.util.ints import uint16
from chia.util.ws_message import create_payload
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import setup_daemon, self_hostname, setup_full_system
from tests.simulation.test_simulation import test_constants_modified
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval

b_tools = BlockTools(constants=test_constants_modified)
b_tools_1 = BlockTools(constants=test_constants_modified)
new_config = b_tools._config
new_config["daemon_port"] = 55401
b_tools.change_config(new_config)


class TestDaemon:
    @pytest.fixture(scope="function")
    async def get_daemon(self):
        async for _ in setup_daemon(btools=b_tools):
            yield _

    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(
            b_tools_1.constants, b_tools=b_tools, b_tools_1=b_tools_1, connect_to_daemon=True
        ):
            yield _

    @pytest.mark.asyncio
    async def test_daemon_simulation(self, simulation, get_daemon):
        node1, node2, _, _, _, _, _, _, _, server1 = simulation
        await server1.start_client(PeerInfo(self_hostname, uint16(21238)))

        async def num_connections():
            count = len(node2.server.connection_by_type[NodeType.FULL_NODE].items())
            return count

        await time_out_assert_custom_interval(60, 1, num_connections, 1)

        await time_out_assert(1500, node_height_at_least, True, node2, 1)
        session = aiohttp.ClientSession()
        crt_path = b_tools.root_path / b_tools.config["daemon_ssl"]["private_crt"]
        key_path = b_tools.root_path / b_tools.config["daemon_ssl"]["private_key"]
        ca_cert_path = b_tools.root_path / b_tools.config["private_ssl_ca"]["crt"]
        ca_key_path = b_tools.root_path / b_tools.config["private_ssl_ca"]["key"]
        ssl_context = ssl_context_for_server(ca_cert_path, ca_key_path, crt_path, key_path)

        ws = await session.ws_connect(
            "wss://127.0.0.1:55401",
            autoclose=True,
            autoping=True,
            heartbeat=60,
            ssl_context=ssl_context,
            max_msg_size=100 * 1024 * 1024,
        )
        service_name = "test_service_name"
        data = {"service": service_name}
        payload = create_payload("register_service", data, service_name, "daemon")
        await ws.send_str(payload)
        message_queue = asyncio.Queue()

        async def reader(ws, queue):
            while True:
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    message = msg.data.strip()
                    message = json.loads(message)
                    await queue.put(message)
                elif msg.type == aiohttp.WSMsgType.PING:
                    await ws.pong()
                elif msg.type == aiohttp.WSMsgType.PONG:
                    continue
                else:
                    if msg.type == aiohttp.WSMsgType.CLOSE:
                        await ws.close()
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        await ws.close()
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        pass

                    break

        read_handler = asyncio.create_task(reader(ws, message_queue))
        data = {}
        payload = create_payload("get_blockchain_state", data, service_name, "chia_full_node")
        await ws.send_str(payload)

        await asyncio.sleep(5)
        blockchain_state_found = False
        while not message_queue.empty():
            message = await message_queue.get()
            if message["command"] == "get_blockchain_state":
                blockchain_state_found = True

        await ws.close()
        read_handler.cancel()
        assert blockchain_state_found
