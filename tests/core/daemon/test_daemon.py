from chia.server.outbound_message import NodeType
from chia.types.peer_info import PeerInfo
from tests.block_tools import BlockTools, create_block_tools, create_block_tools_async
from chia.util.ints import uint16
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
from chia.util.ws_message import create_payload
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import setup_daemon, self_hostname, setup_full_system
from tests.simulation.test_simulation import test_constants_modified
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval
from tests.util.keyring import TempKeyring

import asyncio
import atexit
import json

import aiohttp
import pytest


def cleanup_keyring(keyring: TempKeyring):
    keyring.cleanup()


temp_keyring1 = TempKeyring()
temp_keyring2 = TempKeyring()
atexit.register(cleanup_keyring, temp_keyring1)
atexit.register(cleanup_keyring, temp_keyring2)
b_tools = create_block_tools(constants=test_constants_modified, keychain=temp_keyring1.get_keychain())
b_tools_1 = create_block_tools(constants=test_constants_modified, keychain=temp_keyring2.get_keychain())
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

    @pytest.fixture(scope="function")
    async def get_temp_keyring(self):
        with TempKeyring() as keychain:
            yield keychain

    @pytest.fixture(scope="function")
    async def get_b_tools(self, get_temp_keyring):
        local_b_tools = await create_block_tools_async(constants=test_constants_modified, keychain=get_temp_keyring)
        new_config = local_b_tools._config
        new_config["daemon_port"] = 55401
        local_b_tools.change_config(new_config)
        return local_b_tools

    @pytest.fixture(scope="function")
    async def get_daemon_with_temp_keyring(self, get_b_tools):
        async for _ in setup_daemon(btools=get_b_tools):
            yield get_b_tools

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
        ssl_context = b_tools.get_daemon_ssl_context()

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

    # Suppress warning: "The explicit passing of coroutine objects to asyncio.wait() is deprecated since Python 3.8..."
    # Can be removed when we upgrade to a newer version of websockets (9.1 works)
    @pytest.mark.filterwarnings("ignore::DeprecationWarning:websockets.*")
    @pytest.mark.asyncio
    async def test_validate_keyring_passphrase_rpc(self, get_daemon_with_temp_keyring):
        local_b_tools: BlockTools = get_daemon_with_temp_keyring
        keychain = local_b_tools.local_keychain

        # When: the keychain has a master passphrase set
        keychain.set_master_passphrase(
            current_passphrase=DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, new_passphrase="the correct passphrase"
        )

        async def check_success_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to True
            assert message["data"]["success"] is True

        async def check_bad_passphrase_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to False
            assert message["data"]["success"] is False

        async def check_missing_passphrase_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to False
            assert message["data"]["success"] is False
            # Expect: error string is set
            assert message["data"]["error"] == "missing key"

        async def check_empty_passphrase_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to False
            assert message["data"]["success"] is False

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "wss://127.0.0.1:55401",
                autoclose=True,
                autoping=True,
                heartbeat=60,
                ssl=local_b_tools.get_daemon_ssl_context(),
                max_msg_size=52428800,
            ) as ws:
                # When: using the correct passphrase
                await ws.send_str(
                    create_payload("validate_keyring_passphrase", {"key": "the correct passphrase"}, "test", "daemon")
                )
                # Expect: validation succeeds
                await check_success_case(await ws.receive())

                # When: using the wrong passphrase
                await ws.send_str(
                    create_payload("validate_keyring_passphrase", {"key": "the wrong passphrase"}, "test", "daemon")
                )
                # Expect: validation failure
                await check_bad_passphrase_case(await ws.receive())

                # When: not including the passphrase in the payload
                await ws.send_str(create_payload("validate_keyring_passphrase", {}, "test", "daemon"))
                # Expect: validation failure
                await check_missing_passphrase_case(await ws.receive())

                # When: including an empty passphrase in the payload
                await ws.send_str(create_payload("validate_keyring_passphrase", {"key": ""}, "test", "daemon"))
                # Expect: validation failure
                await check_empty_passphrase_case(await ws.receive())
