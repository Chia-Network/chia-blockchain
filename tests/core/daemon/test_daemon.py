import aiohttp
import asyncio
import json
import logging
import pytest

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Type, Union, cast

from chia.daemon.keychain_server import DeleteLabelRequest, SetLabelRequest
from chia.daemon.server import WebSocketServer, service_plotter
from chia.server.outbound_message import NodeType
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from chia.util.keychain import KeyData
from chia.daemon.keychain_server import GetKeyRequest, GetKeyResponse, GetKeysResponse
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
from chia.util.ws_message import create_payload
from tests.core.node_height import node_height_at_least
from chia.simulator.time_out_assert import time_out_assert_custom_interval, time_out_assert


# Simple class that responds to a poll() call used by WebSocketServer.is_running()
@dataclass
class Service:
    running: bool

    def poll(self) -> Optional[int]:
        return None if self.running else 1


# Mock daemon server that forwards to WebSocketServer
@dataclass
class Daemon:
    # Instance variables used by WebSocketServer.is_running()
    services: Dict[str, Union[List[Service], Service]]
    connections: Dict[str, Optional[List[Any]]]

    def is_service_running(self, service_name: str) -> bool:
        return WebSocketServer.is_service_running(cast(WebSocketServer, self), service_name)

    async def running_services(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return await WebSocketServer.running_services(cast(WebSocketServer, self), request)

    async def is_running(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return await WebSocketServer.is_running(cast(WebSocketServer, self), request)


test_key_data = KeyData.from_mnemonic(
    "grief lock ketchup video day owner torch young work "
    "another venue evidence spread season bright private "
    "tomato remind jaguar original blur embody project can"
)
test_key_data_no_secrets = replace(test_key_data, secrets=None)


success_response_data = {
    "success": True,
}


def fingerprint_missing_response_data(request_type: Type[object]) -> Dict[str, object]:
    return {
        "success": False,
        "error": "malformed request",
        "error_details": {"message": f"1 field missing for {request_type.__name__}: fingerprint"},
    }


def fingerprint_not_found_response_data(fingerprint: int) -> Dict[str, object]:
    return {
        "success": False,
        "error": "key not found",
        "error_details": {
            "fingerprint": fingerprint,
        },
    }


def get_key_response_data(key: KeyData) -> Dict[str, object]:
    return {"success": True, **GetKeyResponse(key=key).to_json_dict()}


def get_keys_response_data(keys: List[KeyData]) -> Dict[str, object]:
    return {"success": True, **GetKeysResponse(keys=keys).to_json_dict()}


def label_missing_response_data(request_type: Type[Any]) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "malformed request",
        "error_details": {"message": f"1 field missing for {request_type.__name__}: label"},
    }


def label_exists_response_data(fingerprint: int, label: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "malformed request",
        "error_details": {"message": f"label {label!r} already exists for fingerprint {str(fingerprint)!r}"},
    }


label_empty_response_data = {
    "success": False,
    "error": "malformed request",
    "error_details": {"message": "label can't be empty or whitespace only"},
}

label_too_long_response_data = {
    "success": False,
    "error": "malformed request",
    "error_details": {"message": "label exceeds max length: 66/65"},
}

label_newline_or_tab_response_data = {
    "success": False,
    "error": "malformed request",
    "error_details": {"message": "label can't contain newline or tab"},
}


def assert_response(response: aiohttp.http_websocket.WSMessage, expected_response_data: Dict[str, Any]) -> None:
    # Expect: JSON response
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    # Expect: daemon handled the request
    assert message["ack"] is True
    # Expect: data matches the expected data
    assert message["data"] == expected_response_data


def assert_running_services_response(response_dict: Dict[str, Any], expected_response_dict: Dict[str, Any]) -> None:
    for k, v in expected_response_dict.items():
        if k == "running_services":
            # Order of services is not guaranteed
            assert len(response_dict[k]) == len(v)
            assert set(response_dict[k]) == set(v)
        else:
            assert response_dict[k] == v


@pytest.fixture(scope="session")
def mock_lonely_daemon():
    # Mock daemon server without any registered services/connections
    return Daemon(services={}, connections={})


@pytest.fixture(scope="session")
def mock_daemon_with_services():
    # Mock daemon server with a couple running services, a plotter, and one stopped service
    return Daemon(
        services={
            "my_refrigerator": Service(True),
            "the_river": Service(True),
            "your_nose": Service(False),
            "chia_plotter": [Service(True), Service(True)],
        },
        connections={},
    )


@pytest.fixture(scope="session")
def mock_daemon_with_services_and_connections():
    # Mock daemon server with a couple running services, a plotter, and a couple active connections
    return Daemon(
        services={
            "my_refrigerator": Service(True),
            "chia_plotter": [Service(True), Service(True)],
            "apple": Service(True),
        },
        connections={
            "apple": [1],
            "banana": [1, 2],
        },
    )


@pytest.mark.asyncio
async def test_daemon_simulation(self_hostname, daemon_simulation):
    deamon_and_nodes, get_b_tools, bt = daemon_simulation
    node1, node2, _, _, _, _, _, _, _, _, daemon1 = deamon_and_nodes
    server1 = node1.full_node.server
    node2_port = node2.full_node.server.get_port()
    await server1.start_client(PeerInfo(self_hostname, uint16(node2_port)))

    async def num_connections():
        count = len(node2.server.get_connections(NodeType.FULL_NODE))
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


@pytest.mark.parametrize(
    "service, expected_result",
    [
        (
            "my_refrigerator",
            False,
        ),
        (
            service_plotter,
            False,
        ),
    ],
)
def test_is_service_running_no_services(mock_lonely_daemon, service, expected_result):
    daemon = mock_lonely_daemon
    assert daemon.is_service_running(service) == expected_result


@pytest.mark.parametrize(
    "service, expected_result",
    [
        (
            "my_refrigerator",
            True,
        ),
        (
            service_plotter,
            True,
        ),
        (
            "your_nose",
            False,
        ),
        (
            "the_river",
            True,
        ),
        (
            "the_clock",
            False,
        ),
    ],
)
def test_is_service_running_with_services(mock_daemon_with_services, service, expected_result):
    daemon = mock_daemon_with_services
    assert daemon.is_service_running(service) == expected_result


@pytest.mark.parametrize(
    "service, expected_result",
    [
        (
            "my_refrigerator",
            True,
        ),
        (
            service_plotter,
            True,
        ),
        (
            "apple",
            True,
        ),
        (
            "banana",
            True,
        ),
        (
            "orange",
            False,
        ),
    ],
)
def test_is_service_running_with_services_and_connections(
    mock_daemon_with_services_and_connections, service, expected_result
):
    daemon = mock_daemon_with_services_and_connections
    assert daemon.is_service_running(service) == expected_result


@pytest.mark.asyncio
async def test_running_services_no_services(mock_lonely_daemon):
    daemon = mock_lonely_daemon
    response = await daemon.running_services({})
    assert_running_services_response(response, {"success": True, "running_services": []})


@pytest.mark.asyncio
async def test_running_services_with_services(mock_daemon_with_services):
    daemon = mock_daemon_with_services
    response = await daemon.running_services({})
    assert_running_services_response(
        response, {"success": True, "running_services": ["my_refrigerator", "the_river", service_plotter]}
    )


@pytest.mark.asyncio
async def test_running_services_with_services_and_connections(mock_daemon_with_services_and_connections):
    daemon = mock_daemon_with_services_and_connections
    response = await daemon.running_services({})
    assert_running_services_response(
        response, {"success": True, "running_services": ["my_refrigerator", "apple", "banana", service_plotter]}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_request, expected_result, expected_exception",
    [
        ({}, None, KeyError),
        (
            {"service": "my_refrigerator"},
            {"success": True, "service_name": "my_refrigerator", "is_running": False},
            None,
        ),
    ],
)
async def test_is_running_no_services(mock_lonely_daemon, service_request, expected_result, expected_exception):
    daemon = mock_lonely_daemon
    if expected_exception is not None:
        with pytest.raises(expected_exception):
            await daemon.is_running(service_request)
    else:
        response = await daemon.is_running(service_request)
        assert response == expected_result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_request, expected_result, expected_exception",
    [
        ({}, None, KeyError),
        (
            {"service": "my_refrigerator"},
            {"success": True, "service_name": "my_refrigerator", "is_running": True},
            None,
        ),
        (
            {"service": "your_nose"},
            {"success": True, "service_name": "your_nose", "is_running": False},
            None,
        ),
        (
            {"service": "the_river"},
            {"success": True, "service_name": "the_river", "is_running": True},
            None,
        ),
        (
            {"service": service_plotter},
            {"success": True, "service_name": service_plotter, "is_running": True},
            None,
        ),
    ],
)
async def test_is_running_with_services(
    mock_daemon_with_services, service_request, expected_result, expected_exception
):
    daemon = mock_daemon_with_services
    if expected_exception is not None:
        with pytest.raises(expected_exception):
            await daemon.is_running(service_request)
    else:
        response = await daemon.is_running(service_request)
        assert response == expected_result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_request, expected_result, expected_exception",
    [
        ({}, None, KeyError),
        (
            {"service": "my_refrigerator"},
            {"success": True, "service_name": "my_refrigerator", "is_running": True},
            None,
        ),
        (
            {"service": "your_nose"},
            {"success": True, "service_name": "your_nose", "is_running": False},
            None,
        ),
        (
            {"service": "apple"},
            {"success": True, "service_name": "apple", "is_running": True},
            None,
        ),
        (
            {"service": "banana"},
            {"success": True, "service_name": "banana", "is_running": True},
            None,
        ),
        (
            {"service": "orange"},
            {"success": True, "service_name": "orange", "is_running": False},
            None,
        ),
    ],
)
async def test_is_running_with_services_and_connections(
    mock_daemon_with_services_and_connections, service_request, expected_result, expected_exception
):
    daemon = mock_daemon_with_services_and_connections
    if expected_exception is not None:
        with pytest.raises(expected_exception):
            await daemon.is_running(service_request)
    else:
        response = await daemon.is_running(service_request)
        assert response == expected_result


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


@pytest.mark.asyncio
async def test_add_private_key_label(daemon_connection_and_temp_keychain):
    ws, keychain = daemon_connection_and_temp_keychain

    async def assert_add_private_key_with_label(key_data: KeyData, request: Dict[str, object]) -> None:
        await ws.send_str(create_payload("add_private_key", request, "test", "daemon"))
        assert_response(await ws.receive(), success_response_data)
        await ws.send_str(
            create_payload("get_key", {"fingerprint": key_data.fingerprint, "include_secrets": True}, "test", "daemon")
        )
        assert_response(await ws.receive(), get_key_response_data(key_data))

    # without `label` parameter
    key_data_0 = KeyData.generate()
    await assert_add_private_key_with_label(key_data_0, {"mnemonic": key_data_0.mnemonic_str()})
    # with `label=None`
    key_data_1 = KeyData.generate()
    await assert_add_private_key_with_label(key_data_1, {"mnemonic": key_data_1.mnemonic_str(), "label": None})
    # with `label="key_2"`
    key_data_2 = KeyData.generate("key_2")
    await assert_add_private_key_with_label(
        key_data_1, {"mnemonic": key_data_2.mnemonic_str(), "label": key_data_2.label}
    )


@pytest.mark.asyncio
async def test_get_key(daemon_connection_and_temp_keychain):
    ws, keychain = daemon_connection_and_temp_keychain

    await ws.send_str(create_payload("get_key", {"fingerprint": test_key_data.fingerprint}, "test", "daemon"))
    assert_response(await ws.receive(), fingerprint_not_found_response_data(test_key_data.fingerprint))

    keychain.add_private_key(test_key_data.mnemonic_str())

    # without `include_secrets`
    await ws.send_str(create_payload("get_key", {"fingerprint": test_key_data.fingerprint}, "test", "daemon"))
    assert_response(await ws.receive(), get_key_response_data(test_key_data_no_secrets))

    # with `include_secrets=False`
    await ws.send_str(
        create_payload(
            "get_key", {"fingerprint": test_key_data.fingerprint, "include_secrets": False}, "test", "daemon"
        )
    )
    assert_response(await ws.receive(), get_key_response_data(test_key_data_no_secrets))

    # with `include_secrets=True`
    await ws.send_str(
        create_payload("get_key", {"fingerprint": test_key_data.fingerprint, "include_secrets": True}, "test", "daemon")
    )
    assert_response(await ws.receive(), get_key_response_data(test_key_data))

    await ws.send_str(create_payload("get_key", {}, "test", "daemon"))
    assert_response(await ws.receive(), fingerprint_missing_response_data(GetKeyRequest))

    await ws.send_str(create_payload("get_key", {"fingerprint": 123456}, "test", "daemon"))
    assert_response(await ws.receive(), fingerprint_not_found_response_data(123456))


@pytest.mark.asyncio
async def test_get_keys(daemon_connection_and_temp_keychain):
    ws, keychain = daemon_connection_and_temp_keychain

    # empty keychain
    await ws.send_str(create_payload("get_keys", {}, "test", "daemon"))
    assert_response(await ws.receive(), get_keys_response_data([]))

    keys = [KeyData.generate() for _ in range(5)]
    keys_added = []
    for key_data in keys:
        keychain.add_private_key(key_data.mnemonic_str())
        keys_added.append(key_data)

        get_keys_response_data_without_secrets = get_keys_response_data(
            [replace(key, secrets=None) for key in keys_added]
        )

        # without `include_secrets`
        await ws.send_str(create_payload("get_keys", {}, "test", "daemon"))
        assert_response(await ws.receive(), get_keys_response_data_without_secrets)

        # with `include_secrets=False`
        await ws.send_str(create_payload("get_keys", {"include_secrets": False}, "test", "daemon"))
        assert_response(await ws.receive(), get_keys_response_data_without_secrets)

        # with `include_secrets=True`
        await ws.send_str(create_payload("get_keys", {"include_secrets": True}, "test", "daemon"))
        assert_response(await ws.receive(), get_keys_response_data(keys_added))


@pytest.mark.asyncio
async def test_key_renaming(daemon_connection_and_temp_keychain):
    ws, keychain = daemon_connection_and_temp_keychain
    keychain.add_private_key(test_key_data.mnemonic_str())
    # Rename the key three times
    for i in range(3):
        key_data = replace(test_key_data_no_secrets, label=f"renaming_{i}")
        await ws.send_str(
            create_payload(
                "set_label", {"fingerprint": key_data.fingerprint, "label": key_data.label}, "test", "daemon"
            )
        )
        assert_response(await ws.receive(), success_response_data)

        await ws.send_str(create_payload("get_key", {"fingerprint": key_data.fingerprint}, "test", "daemon"))
        assert_response(
            await ws.receive(),
            {
                "success": True,
                "key": key_data.to_json_dict(),
            },
        )


@pytest.mark.asyncio
async def test_key_label_deletion(daemon_connection_and_temp_keychain):
    ws, keychain = daemon_connection_and_temp_keychain

    keychain.add_private_key(test_key_data.mnemonic_str(), "key_0")
    assert keychain.get_key(test_key_data.fingerprint).label == "key_0"
    await ws.send_str(create_payload("delete_label", {"fingerprint": test_key_data.fingerprint}, "test", "daemon"))
    assert_response(await ws.receive(), success_response_data)
    assert keychain.get_key(test_key_data.fingerprint).label is None
    await ws.send_str(create_payload("delete_label", {"fingerprint": test_key_data.fingerprint}, "test", "daemon"))
    assert_response(await ws.receive(), fingerprint_not_found_response_data(test_key_data.fingerprint))


@pytest.mark.parametrize(
    "method, parameter, response_data_dict",
    [
        (
            "set_label",
            {"fingerprint": test_key_data.fingerprint, "label": "new_label"},
            success_response_data,
        ),
        (
            "set_label",
            {"label": "new_label"},
            fingerprint_missing_response_data(SetLabelRequest),
        ),
        (
            "set_label",
            {"fingerprint": test_key_data.fingerprint},
            label_missing_response_data(SetLabelRequest),
        ),
        (
            "set_label",
            {"fingerprint": test_key_data.fingerprint, "label": ""},
            label_empty_response_data,
        ),
        (
            "set_label",
            {"fingerprint": test_key_data.fingerprint, "label": "a" * 66},
            label_too_long_response_data,
        ),
        (
            "set_label",
            {"fingerprint": test_key_data.fingerprint, "label": "a\nb"},
            label_newline_or_tab_response_data,
        ),
        (
            "set_label",
            {"fingerprint": test_key_data.fingerprint, "label": "a\tb"},
            label_newline_or_tab_response_data,
        ),
        (
            "set_label",
            {"fingerprint": test_key_data.fingerprint, "label": "key_0"},
            label_exists_response_data(test_key_data.fingerprint, "key_0"),
        ),
        (
            "delete_label",
            {"fingerprint": test_key_data.fingerprint},
            success_response_data,
        ),
        (
            "delete_label",
            {},
            fingerprint_missing_response_data(DeleteLabelRequest),
        ),
        (
            "delete_label",
            {"fingerprint": 123456},
            fingerprint_not_found_response_data(123456),
        ),
    ],
)
@pytest.mark.asyncio
async def test_key_label_methods(
    daemon_connection_and_temp_keychain, method: str, parameter: Dict[str, Any], response_data_dict: Dict[str, Any]
) -> None:
    ws, keychain = daemon_connection_and_temp_keychain
    keychain.add_private_key(test_key_data.mnemonic_str(), "key_0")
    await ws.send_str(create_payload(method, parameter, "test", "daemon"))
    assert_response(await ws.receive(), response_data_dict)
