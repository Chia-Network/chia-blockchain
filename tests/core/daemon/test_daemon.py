import aiohttp
import asyncio
import json
import logging
import pytest
import pytest_asyncio

from chia.daemon.server import WebSocketServer
from chia.server.outbound_message import NodeType
from chia.types.peer_info import PeerInfo
from tests.block_tools import BlockTools, create_block_tools_async
from chia.util.ints import uint16
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
from chia.util.ws_message import create_payload
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import setup_daemon, setup_full_system
from tests.simulation.test_simulation import test_constants_modified
from tests.time_out_assert import time_out_assert_custom_interval, time_out_assert
from tests.util.keyring import TempKeyring


@pytest_asyncio.fixture(scope="function")
async def get_temp_keyring():
    with TempKeyring() as keychain:
        yield keychain


@pytest_asyncio.fixture(scope="function")
async def get_b_tools_1(get_temp_keyring):
    return await create_block_tools_async(constants=test_constants_modified, keychain=get_temp_keyring)


@pytest_asyncio.fixture(scope="function")
async def get_b_tools(get_temp_keyring):
    local_b_tools = await create_block_tools_async(constants=test_constants_modified, keychain=get_temp_keyring)
    new_config = local_b_tools._config
    local_b_tools.change_config(new_config)
    return local_b_tools


@pytest_asyncio.fixture(scope="function")
async def get_daemon_with_temp_keyring(get_b_tools):
    async for daemon in setup_daemon(btools=get_b_tools):
        yield get_b_tools, daemon


# TODO: Ideally, the db_version should be the (parameterized) db_version
# fixture, to test all versions of the database schema. This doesn't work
# because of a hack in shutting down the full node, which means you cannot run
# more than one simulations per process.
@pytest_asyncio.fixture(scope="function")
async def simulation(bt, get_b_tools, get_b_tools_1):
    async for _ in setup_full_system(
        test_constants_modified,
        bt,
        b_tools=get_b_tools,
        b_tools_1=get_b_tools_1,
        connect_to_daemon=True,
        db_version=1,
    ):
        yield _


class TestDaemon:
    @pytest.mark.asyncio
    async def test_daemon_simulation(self, self_hostname, simulation, bt, get_b_tools, get_b_tools_1):
        node1, node2, _, _, _, _, _, _, _, _, server1, daemon1 = simulation
        node2_port = node2.full_node.config["port"]
        await server1.start_client(PeerInfo(self_hostname, uint16(node2_port)))

        async def num_connections():
            count = len(node2.server.connection_by_type[NodeType.FULL_NODE].items())
            return count

        await time_out_assert_custom_interval(60, 1, num_connections, 1)

        await time_out_assert(1500, node_height_at_least, True, node2, 1)

        session = aiohttp.ClientSession()

        log = logging.getLogger()
        log.warning(f"Connecting to daemon on port {daemon1.daemon_port}")
        ws = await session.ws_connect(
            f"wss://127.0.0.1:{daemon1.daemon_port}",
            autoclose=True,
            autoping=True,
            heartbeat=60,
            ssl_context=get_b_tools.get_daemon_ssl_context(),
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
        local_b_tools: BlockTools = get_daemon_with_temp_keyring[0]
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
                f"wss://127.0.0.1:{local_b_tools._config['daemon_port']}",
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

    # Suppress warning: "The explicit passing of coroutine objects to asyncio.wait() is deprecated since Python 3.8..."
    # Can be removed when we upgrade to a newer version of websockets (9.1 works)
    @pytest.mark.filterwarnings("ignore::DeprecationWarning:websockets.*")
    @pytest.mark.asyncio
    async def test_add_private_key(self, get_daemon_with_temp_keyring):
        local_b_tools: BlockTools = get_daemon_with_temp_keyring[0]
        daemon: WebSocketServer = get_daemon_with_temp_keyring[1]
        keychain = daemon.keychain_server._default_keychain  # Keys will be added here
        test_mnemonic = (
            "grief lock ketchup video day owner torch young work "
            "another venue evidence spread season bright private "
            "tomato remind jaguar original blur embody project can"
        )
        test_fingerprint = 2877570395
        mnemonic_with_typo = f"{test_mnemonic}xyz"  # intentional typo: can -> canxyz
        mnemonic_with_missing_word = " ".join(test_mnemonic.split(" ")[:-1])  # missing last word

        async def check_success_case(response: aiohttp.http_websocket.WSMessage):
            nonlocal keychain

            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to True
            assert message["data"]["success"] is True
            # Expect: the keychain has the new key
            assert keychain.get_private_key_by_fingerprint(test_fingerprint) is not None

        async def check_missing_param_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to False
            assert message["data"]["success"] is False
            # Expect: error field is set to "malformed request"
            assert message["data"]["error"] == "malformed request"
            # Expect: error_details message is set to "missing mnemonic and/or passphrase"
            assert message["data"]["error_details"]["message"] == "missing mnemonic and/or passphrase"

        async def check_mnemonic_with_typo_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to False
            assert message["data"]["success"] is False
            # Expect: error field is set to "'canxyz' is not in the mnemonic dictionary; may be misspelled"
            assert message["data"]["error"] == "'canxyz' is not in the mnemonic dictionary; may be misspelled"

        async def check_invalid_mnemonic_length_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to False
            assert message["data"]["success"] is False
            # Expect: error field is set to "Invalid mnemonic length"
            assert message["data"]["error"] == "Invalid mnemonic length"

        async def check_invalid_mnemonic_case(response: aiohttp.http_websocket.WSMessage):
            # Expect: JSON response
            assert response.type == aiohttp.WSMsgType.TEXT
            message = json.loads(response.data.strip())
            # Expect: daemon handled the request
            assert message["ack"] is True
            # Expect: success flag is set to False
            assert message["data"]["success"] is False
            # Expect: error field is set to "Invalid order of mnemonic words"
            assert message["data"]["error"] == "Invalid order of mnemonic words"

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                f"wss://127.0.0.1:{local_b_tools._config['daemon_port']}",
                autoclose=True,
                autoping=True,
                heartbeat=60,
                ssl=local_b_tools.get_daemon_ssl_context(),
                max_msg_size=52428800,
            ) as ws:
                # Expect the key hasn't been added yet
                assert keychain.get_private_key_by_fingerprint(test_fingerprint) is None

                await ws.send_str(
                    create_payload("add_private_key", {"mnemonic": test_mnemonic, "passphrase": ""}, "test", "daemon")
                )
                # Expect: key was added successfully
                await check_success_case(await ws.receive())

                # When: missing mnemonic
                await ws.send_str(create_payload("add_private_key", {"passphrase": ""}, "test", "daemon"))
                # Expect: Failure due to missing mnemonic
                await check_missing_param_case(await ws.receive())

                # When: missing passphrase
                await ws.send_str(create_payload("add_private_key", {"mnemonic": test_mnemonic}, "test", "daemon"))
                # Expect: Failure due to missing passphrase
                await check_missing_param_case(await ws.receive())

                # When: using a mmnemonic with an incorrect word (typo)
                await ws.send_str(
                    create_payload(
                        "add_private_key", {"mnemonic": mnemonic_with_typo, "passphrase": ""}, "test", "daemon"
                    )
                )
                # Expect: Failure due to misspelled mnemonic
                await check_mnemonic_with_typo_case(await ws.receive())

                # When: using a mnemonic with an incorrect word count
                await ws.send_str(
                    create_payload(
                        "add_private_key", {"mnemonic": mnemonic_with_missing_word, "passphrase": ""}, "test", "daemon"
                    )
                )
                # Expect: Failure due to invalid mnemonic
                await check_invalid_mnemonic_length_case(await ws.receive())

                # When: using an incorrect mnemnonic
                await ws.send_str(
                    create_payload(
                        "add_private_key", {"mnemonic": " ".join(["abandon"] * 24), "passphrase": ""}, "test", "daemon"
                    )
                )
                # Expect: Failure due to checksum error
                await check_invalid_mnemonic_case(await ws.receive())
