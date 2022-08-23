import aiohttp
import asyncio
import json
import logging
import pytest

from typing import Any, Dict

from chia.server.outbound_message import NodeType
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from chia.util.keychain import KeyData
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
from chia.util.ws_message import create_payload
from tests.core.node_height import node_height_at_least
from chia.simulator.time_out_assert import time_out_assert_custom_interval, time_out_assert

test_key_data = KeyData.from_mnemonic(
    "grief lock ketchup video day owner torch young work "
    "another venue evidence spread season bright private "
    "tomato remind jaguar original blur embody project can"
)

success_response_data = {
    "success": True,
}


def assert_response(response: aiohttp.http_websocket.WSMessage, expected_response_data: Dict[str, Any]) -> None:
    # Expect: JSON response
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    # Expect: daemon handled the request
    assert message["ack"] is True
    # Expect: data matches the expected data
    assert message["data"] == expected_response_data


@pytest.mark.asyncio
async def test_daemon_simulation(self_hostname, daemon_simulation):
    deamon_and_nodes, get_b_tools, bt = daemon_simulation
    node1, node2, _, _, _, _, _, _, _, _, daemon1 = deamon_and_nodes
    server1 = node1.full_node.server
    node2_port = node2.full_node.server.get_port()
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
            # ClientWebSocketReponse::receive() internally handles PING, PONG, and CLOSE messages
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                message = msg.data.strip()
                message = json.loads(message)
                await queue.put(message)
            else:
                if msg.type == aiohttp.WSMsgType.ERROR:
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


@pytest.mark.asyncio
async def test_validate_keyring_passphrase_rpc(daemon_connection_and_temp_keychain):
    ws, keychain = daemon_connection_and_temp_keychain

    # When: the keychain has a master passphrase set
    keychain.set_master_passphrase(
        current_passphrase=DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, new_passphrase="the correct passphrase"
    )

    bad_passphrase_case_response_data = {
        "success": False,
        "error": None,
    }

    missing_passphrase_response_data = {
        "success": False,
        "error": "missing key",
    }

    empty_passphrase_response_data = {
        "success": False,
        "error": None,
    }

    # When: using the correct passphrase
    await ws.send_str(
        create_payload("validate_keyring_passphrase", {"key": "the correct passphrase"}, "test", "daemon")
    )
    # Expect: validation succeeds
    # TODO: unify error responses in the server, sometimes we add `error: None` sometimes not.
    assert_response(await ws.receive(), {**success_response_data, "error": None})

    # When: using the wrong passphrase
    await ws.send_str(create_payload("validate_keyring_passphrase", {"key": "the wrong passphrase"}, "test", "daemon"))
    # Expect: validation failure
    assert_response(await ws.receive(), bad_passphrase_case_response_data)

    # When: not including the passphrase in the payload
    await ws.send_str(create_payload("validate_keyring_passphrase", {}, "test", "daemon"))
    # Expect: validation failure
    assert_response(await ws.receive(), missing_passphrase_response_data)

    # When: including an empty passphrase in the payload
    await ws.send_str(create_payload("validate_keyring_passphrase", {"key": ""}, "test", "daemon"))
    # Expect: validation failure
    assert_response(await ws.receive(), empty_passphrase_response_data)


@pytest.mark.asyncio
async def test_add_private_key(daemon_connection_and_temp_keychain):
    ws, keychain = daemon_connection_and_temp_keychain

    mnemonic_with_typo = f"{test_key_data.mnemonic_str()}xyz"  # intentional typo: can -> canxyz
    mnemonic_with_missing_word = " ".join(test_key_data.mnemonic_str()[:-1])  # missing last word

    missing_mnemonic_response_data = {
        "success": False,
        "error": "malformed request",
        "error_details": {"message": "missing mnemonic"},
    }

    mnemonic_with_typo_response_data = {
        "success": False,
        "error": "'canxyz' is not in the mnemonic dictionary; may be misspelled",
    }

    invalid_mnemonic_length_response_data = {
        "success": False,
        "error": "Invalid mnemonic length",
    }

    invalid_mnemonic_response_data = {
        "success": False,
        "error": "Invalid order of mnemonic words",
    }

    # Expect the key hasn't been added yet
    assert keychain.get_private_key_by_fingerprint(test_key_data.fingerprint) is None

    await ws.send_str(create_payload("add_private_key", {"mnemonic": test_key_data.mnemonic_str()}, "test", "daemon"))
    # Expect: key was added successfully
    assert_response(await ws.receive(), success_response_data)

    # When: missing mnemonic
    await ws.send_str(create_payload("add_private_key", {}, "test", "daemon"))
    # Expect: Failure due to missing mnemonic
    assert_response(await ws.receive(), missing_mnemonic_response_data)

    # When: using a mmnemonic with an incorrect word (typo)
    await ws.send_str(create_payload("add_private_key", {"mnemonic": mnemonic_with_typo}, "test", "daemon"))
    # Expect: Failure due to misspelled mnemonic
    assert_response(await ws.receive(), mnemonic_with_typo_response_data)

    # When: using a mnemonic with an incorrect word count
    await ws.send_str(create_payload("add_private_key", {"mnemonic": mnemonic_with_missing_word}, "test", "daemon"))
    # Expect: Failure due to invalid mnemonic
    assert_response(await ws.receive(), invalid_mnemonic_length_response_data)

    # When: using an incorrect mnemnonic
    await ws.send_str(create_payload("add_private_key", {"mnemonic": " ".join(["abandon"] * 24)}, "test", "daemon"))
    # Expect: Failure due to checksum error
    assert_response(await ws.receive(), invalid_mnemonic_response_data)
