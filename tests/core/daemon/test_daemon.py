from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast

import aiohttp
import pkg_resources
import pytest
from aiohttp.web_ws import WebSocketResponse

from chia.daemon.client import connect_to_daemon
from chia.daemon.keychain_server import (
    DeleteLabelRequest,
    GetKeyRequest,
    GetKeyResponse,
    GetKeysResponse,
    SetLabelRequest,
)
from chia.daemon.server import WebSocketServer, plotter_log_path, service_plotter
from chia.server.outbound_message import NodeType
from chia.simulator.block_tools import BlockTools
from chia.simulator.keyring import TempKeyring
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_custom_interval
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config
from chia.util.ints import uint16
from chia.util.json_util import dict_to_json_str
from chia.util.keychain import Keychain, KeyData, supports_os_passphrase_storage
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, KeyringWrapper
from chia.util.ws_message import create_payload, create_payload_dict
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk
from tests.core.node_height import node_height_at_least
from tests.util.misc import Marks, datacases

chiapos_version = pkg_resources.get_distribution("chiapos").version


@dataclass
class RouteCase:
    route: str
    description: str
    request: Dict[str, Any]
    response: Dict[str, Any]
    marks: Marks = ()

    @property
    def id(self) -> str:
        return f"{self.route}: {self.description}"


@dataclass
class WalletAddressCase:
    id: str
    request: Dict[str, Any]
    response: Dict[str, Any]
    pubkeys_only: bool = field(default=False)
    marks: Marks = ()


@dataclass
class KeysForPlotCase:
    id: str
    request: Dict[str, Any]
    response: Dict[str, Any]
    marks: Marks = ()


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

    # Instance variables used by WebSocketServer.get_wallet_addresses()
    net_config: Dict[str, Any] = field(default_factory=dict)

    def get_command_mapping(self) -> Dict[str, Any]:
        return {
            "get_routes": None,
            "example_one": None,
            "example_two": None,
            "example_three": None,
        }

    def is_service_running(self, service_name: str) -> bool:
        return WebSocketServer.is_service_running(cast(WebSocketServer, self), service_name)

    async def running_services(self) -> Dict[str, Any]:
        return await WebSocketServer.running_services(cast(WebSocketServer, self))

    async def is_running(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return await WebSocketServer.is_running(cast(WebSocketServer, self), request)

    async def get_routes(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return await WebSocketServer.get_routes(
            cast(WebSocketServer, self), websocket=WebSocketResponse(), request=request
        )

    async def get_wallet_addresses(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return await WebSocketServer.get_wallet_addresses(
            cast(WebSocketServer, self), websocket=WebSocketResponse(), request=request
        )

    async def get_keys_for_plotting(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return await WebSocketServer.get_keys_for_plotting(
            cast(WebSocketServer, self), websocket=WebSocketResponse(), request=request
        )


test_key_data = KeyData.from_mnemonic(
    "grief lock ketchup video day owner torch young work "
    "another venue evidence spread season bright private "
    "tomato remind jaguar original blur embody project can"
)
test_key_data_no_secrets = replace(test_key_data, secrets=None)

test_key_data_2 = KeyData.from_mnemonic(
    "banana boat fragile ghost fortune beyond aerobic access "
    "hammer stable page grunt venture purse canyon discover "
    "egg vivid spare immune awake code announce message"
)

success_response_data = {
    "success": True,
}

plotter_request_ref = {
    "service": "chia_plotter",
    "plotter": "chiapos",
    "k": 25,
    "r": 2,
    "u": 128,
    "e": True,
    "parallel": False,
    "n": 1,
    "queue": "default",
    "d": "unknown",
    "t": "unknown",
    "t2": "",
    "f": "",
    "plotNFTContractAddr": "",
    "x": True,
    "b": 512,
    "overrideK": True,
    "delay": 0,
    "a": 3598820529,
    "c": "xxx",
}


def add_private_key_response_data(fingerprint: int) -> Dict[str, object]:
    return {
        "success": True,
        "fingerprint": fingerprint,
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


def assert_response(
    response: aiohttp.http_websocket.WSMessage, expected_response_data: Dict[str, Any], request_id: Optional[str] = None
) -> None:
    # Expect: JSON response
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    # Expect: daemon handled the request
    assert message["ack"] is True
    if request_id is not None:
        assert message["request_id"] == request_id
    # Expect: data matches the expected data
    assert message["data"] == expected_response_data


def assert_response_success_only(response: aiohttp.http_websocket.WSMessage, request_id: Optional[str] = None) -> None:
    # Expect: JSON response
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    # Expect: {"success": True}
    if request_id is not None:
        assert message["request_id"] == request_id
    assert message["data"]["success"] is True


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
    return Daemon(services={}, connections={}, net_config={})


@pytest.fixture(scope="session")
def mock_daemon_with_services():
    # Mock daemon server with a couple running services, a plotter, and one stopped service
    return Daemon(
        services={
            "my_refrigerator": [Service(True)],
            "the_river": [Service(True)],
            "your_nose": [Service(False)],
            "chia_plotter": [Service(True), Service(True)],
        },
        connections={},
        net_config={},
    )


@pytest.fixture(scope="session")
def mock_daemon_with_services_and_connections():
    # Mock daemon server with a couple running services, a plotter, and a couple active connections
    return Daemon(
        services={
            "my_refrigerator": [Service(True)],
            "chia_plotter": [Service(True), Service(True)],
            "apple": [Service(True)],
        },
        connections={
            "apple": [1],
            "banana": [1, 2],
        },
        net_config={},
    )


@pytest.fixture(scope="function")
def get_keychain_for_function():
    with TempKeyring() as keychain:
        yield keychain
        KeyringWrapper.cleanup_shared_instance()


@pytest.fixture(scope="function")
def mock_daemon_with_config_and_keys(get_keychain_for_function, root_path_populated_with_config):
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml")
    keychain = Keychain()

    # populate the keychain with some test keys
    keychain.add_private_key(test_key_data.mnemonic_str())
    keychain.add_private_key(test_key_data_2.mnemonic_str())

    # Mock daemon server with net_config set for mainnet
    return Daemon(services={}, connections={}, net_config=config)


@pytest.fixture(scope="function")
async def daemon_client_with_config_and_keys(get_keychain_for_function, get_daemon, bt):
    keychain = Keychain()

    # populate the keychain with some test keys
    keychain.add_private_key(test_key_data.mnemonic_str())
    keychain.add_private_key(test_key_data_2.mnemonic_str())

    daemon = get_daemon
    client = await connect_to_daemon(
        daemon.self_hostname,
        daemon.daemon_port,
        50 * 1000 * 1000,
        bt.get_daemon_ssl_context(),
        heartbeat=daemon.heartbeat,
    )
    return client


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
    response = await daemon.running_services()
    assert_running_services_response(response, {"success": True, "running_services": []})


@pytest.mark.asyncio
async def test_running_services_with_services(mock_daemon_with_services):
    daemon = mock_daemon_with_services
    response = await daemon.running_services()
    assert_running_services_response(
        response, {"success": True, "running_services": ["my_refrigerator", "the_river", service_plotter]}
    )


@pytest.mark.asyncio
async def test_running_services_with_services_and_connections(mock_daemon_with_services_and_connections):
    daemon = mock_daemon_with_services_and_connections
    response = await daemon.running_services()
    assert_running_services_response(
        response, {"success": True, "running_services": ["my_refrigerator", "apple", "banana", service_plotter]}
    )


@pytest.mark.asyncio
async def test_get_routes(mock_lonely_daemon):
    daemon = mock_lonely_daemon
    response = await daemon.get_routes({})
    assert response == {
        "success": True,
        "routes": ["get_routes", "example_one", "example_two", "example_three"],
    }


@datacases(
    WalletAddressCase(
        id="no params",
        request={},
        response={
            "success": True,
            "wallet_addresses": {
                test_key_data.fingerprint: [
                    {
                        "address": "xch1zze67l3jgxuvyaxhjhu7326sezxxve7lgzvq0497ddggzhff7c9s2pdcwh",
                        "hd_path": "m/12381/8444/2/0",
                    },
                ],
                test_key_data_2.fingerprint: [
                    {
                        "address": "xch1fra5h0qnsezrxenjyslyxx7y4l268gq52m0rgenh58vn8f577uzswzvk4v",
                        "hd_path": "m/12381/8444/2/0",
                    }
                ],
            },
        },
    ),
    WalletAddressCase(
        id="list of fingerprints",
        request={"fingerprints": [test_key_data.fingerprint]},
        response={
            "success": True,
            "wallet_addresses": {
                test_key_data.fingerprint: [
                    {
                        "address": "xch1zze67l3jgxuvyaxhjhu7326sezxxve7lgzvq0497ddggzhff7c9s2pdcwh",
                        "hd_path": "m/12381/8444/2/0",
                    },
                ],
            },
        },
    ),
    WalletAddressCase(
        id="count and index",
        request={"fingerprints": [test_key_data.fingerprint], "count": 2, "index": 1},
        response={
            "success": True,
            "wallet_addresses": {
                test_key_data.fingerprint: [
                    {
                        "address": "xch16jqcaguq27z8xvpu89j7eaqfzn6k89hdrrlm0rffku85n8n7m7sqqmmahh",
                        "hd_path": "m/12381/8444/2/1",
                    },
                    {
                        "address": "xch1955vj0gx5tqe7v5tceajn2p4z4pup8d4g2exs0cz4xjqses8ru6qu8zp3y",
                        "hd_path": "m/12381/8444/2/2",
                    },
                ]
            },
        },
    ),
    WalletAddressCase(
        id="hardened derivations",
        request={"fingerprints": [test_key_data.fingerprint], "non_observer_derivation": True},
        response={
            "success": True,
            "wallet_addresses": {
                test_key_data.fingerprint: [
                    {
                        "address": "xch1k996a7h3agygjhqtrf0ycpa7wfd6k5ye2plkf54ukcmdj44gkqkq880l7n",
                        "hd_path": "m/12381n/8444n/2n/0n",
                    }
                ]
            },
        },
    ),
    WalletAddressCase(
        id="invalid fingerprint",
        request={"fingerprints": [999999]},
        response={
            "success": False,
            "error": "key(s) not found for fingerprint(s) {999999}",
        },
    ),
    WalletAddressCase(
        id="missing private key",
        request={"fingerprints": [test_key_data.fingerprint]},
        response={
            "success": False,
            "error": f"missing private key for key with fingerprint {test_key_data.fingerprint}",
        },
        pubkeys_only=True,
    ),
)
@pytest.mark.asyncio
async def test_get_wallet_addresses(
    mock_daemon_with_config_and_keys,
    monkeypatch,
    case: WalletAddressCase,
):
    daemon = mock_daemon_with_config_and_keys

    original_get_keys = Keychain.get_keys

    def get_keys_no_secrets(self, include_secrets):
        return original_get_keys(self, include_secrets=False)

    # in the pubkeys_only case, we're ensuring that only pubkeys are returned by get_keys,
    # which will have the effect of causing get_wallet_addresses to raise an exception
    if case.pubkeys_only:
        # monkeypatch Keychain.get_keys() to always call get_keys() with include_secrets=False
        monkeypatch.setattr(Keychain, "get_keys", get_keys_no_secrets)

    assert case.response == await daemon.get_wallet_addresses(case.request)


@datacases(
    KeysForPlotCase(
        id="no params",
        # When not specifying exact fingerprints, `get_keys_for_plotting` returns
        # all farmer_pk/pool_pk data for available fingerprints
        request={},
        response={
            "success": True,
            "keys": {
                test_key_data.fingerprint: {
                    "farmer_public_key": bytes(master_sk_to_farmer_sk(test_key_data.private_key).get_g1()).hex(),
                    "pool_public_key": bytes(master_sk_to_pool_sk(test_key_data.private_key).get_g1()).hex(),
                },
                test_key_data_2.fingerprint: {
                    "farmer_public_key": bytes(master_sk_to_farmer_sk(test_key_data_2.private_key).get_g1()).hex(),
                    "pool_public_key": bytes(master_sk_to_pool_sk(test_key_data_2.private_key).get_g1()).hex(),
                },
            },
        },
    ),
    KeysForPlotCase(
        id="list of fingerprints",
        request={"fingerprints": [test_key_data.fingerprint]},
        response={
            "success": True,
            "keys": {
                test_key_data.fingerprint: {
                    "farmer_public_key": bytes(master_sk_to_farmer_sk(test_key_data.private_key).get_g1()).hex(),
                    "pool_public_key": bytes(master_sk_to_pool_sk(test_key_data.private_key).get_g1()).hex(),
                },
            },
        },
    ),
    KeysForPlotCase(
        id="invalid fingerprint",
        request={"fingerprints": [999999]},
        response={
            "success": False,
            "error": "key(s) not found for fingerprint(s) {999999}",
        },
    ),
)
@pytest.mark.asyncio
async def test_get_keys_for_plotting(
    mock_daemon_with_config_and_keys,
    monkeypatch,
    case: KeysForPlotCase,
):
    daemon = mock_daemon_with_config_and_keys
    assert case.response == await daemon.get_keys_for_plotting(case.request)


@datacases(
    KeysForPlotCase(
        id="invalid request format",
        request={"fingerprints": test_key_data.fingerprint},
        response={},
    ),
)
@pytest.mark.asyncio
async def test_get_keys_for_plotting_error(
    mock_daemon_with_config_and_keys,
    monkeypatch,
    case: KeysForPlotCase,
):
    daemon = mock_daemon_with_config_and_keys
    with pytest.raises(ValueError, match="fingerprints must be a list of integer"):
        await daemon.get_keys_for_plotting(case.request)


@pytest.mark.asyncio
async def test_get_keys_for_plotting_client(daemon_client_with_config_and_keys):
    client = await daemon_client_with_config_and_keys
    response = await client.get_keys_for_plotting()
    assert response["data"]["success"] is True
    assert len(response["data"]["keys"]) == 2
    assert str(test_key_data.fingerprint) in response["data"]["keys"]
    assert str(test_key_data_2.fingerprint) in response["data"]["keys"]
    response = await client.get_keys_for_plotting([test_key_data.fingerprint])
    assert response["data"]["success"] is True
    assert len(response["data"]["keys"]) == 1
    assert str(test_key_data.fingerprint) in response["data"]["keys"]
    assert str(test_key_data_2.fingerprint) not in response["data"]["keys"]
    await client.close()


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
    assert_response(await ws.receive(), add_private_key_response_data(test_key_data.fingerprint))

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

    async def assert_add_private_key_with_label(
        key_data: KeyData, request: Dict[str, object], add_private_key_response: Dict[str, object]
    ) -> None:
        await ws.send_str(create_payload("add_private_key", request, "test", "daemon"))
        assert_response(await ws.receive(), add_private_key_response)
        await ws.send_str(
            create_payload("get_key", {"fingerprint": key_data.fingerprint, "include_secrets": True}, "test", "daemon")
        )
        assert_response(await ws.receive(), get_key_response_data(key_data))

    # without `label` parameter
    key_data_0 = KeyData.generate()
    await assert_add_private_key_with_label(
        key_data_0,
        {"mnemonic": key_data_0.mnemonic_str()},
        add_private_key_response_data(key_data_0.fingerprint),
    )
    # with `label=None`
    key_data_1 = KeyData.generate()
    await assert_add_private_key_with_label(
        key_data_1,
        {"mnemonic": key_data_1.mnemonic_str(), "label": None},
        add_private_key_response_data(key_data_1.fingerprint),
    )
    # with `label="key_2"`
    key_data_2 = KeyData.generate("key_2")
    await assert_add_private_key_with_label(
        key_data_1,
        {"mnemonic": key_data_2.mnemonic_str(), "label": key_data_2.label},
        add_private_key_response_data(key_data_2.fingerprint),
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


@pytest.mark.asyncio
async def test_bad_json(daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain]) -> None:
    ws, _ = daemon_connection_and_temp_keychain

    await ws.send_str("{doo: '12'}")  # send some bad json
    response = await ws.receive()

    # check for error response
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    assert message["data"]["success"] is False
    assert message["data"]["error"].startswith("Expecting property name")

    # properly register a service
    service_name = "test_service"
    data = {"service": service_name}
    payload = create_payload("register_service", data, service_name, "daemon")
    await ws.send_str(payload)
    await ws.receive()

    # send some more bad json
    await ws.send_str("{doo: '12'}")  # send some bad json
    response = await ws.receive()
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    assert message["command"] != "register_service"
    assert message["data"]["success"] is False
    assert message["data"]["error"].startswith("Expecting property name")


@datacases(
    RouteCase(
        route="register_service",
        description="no service name",
        request={
            "fred": "barney",
        },
        response={"success": False},
    ),
    RouteCase(
        route="register_service",
        description="chia_plotter",
        request={
            "service": "chia_plotter",
        },
        response={"success": True, "service": "chia_plotter", "queue": []},
    ),
    RouteCase(
        route="unknown_command",
        description="non-existant route",
        request={},
        response={"success": False, "error": "unknown_command unknown_command"},
    ),
    RouteCase(
        route="running_services",
        description="successful",
        request={},
        response={"success": True, "running_services": []},
    ),
    RouteCase(
        route="keyring_status",
        description="successful",
        request={},
        response={
            "can_save_passphrase": supports_os_passphrase_storage(),
            "can_set_passphrase_hint": True,
            "is_keyring_locked": False,
            "passphrase_hint": "",
            "passphrase_requirements": {"is_optional": True, "min_length": 8},
            "success": True,
            "user_passphrase_is_set": False,
        },
    ),
    RouteCase(
        route="get_status",
        description="successful",
        request={},
        response={"success": True, "genesis_initialized": True},
    ),
    RouteCase(
        route="get_plotters",
        description="successful",
        request={},
        response={
            "success": True,
            "plotters": {
                "bladebit": {
                    "can_install": True,
                    "cuda_support": False,
                    "display_name": "BladeBit Plotter",
                    "installed": False,
                },
                "chiapos": {"display_name": "Chia Proof of Space", "installed": True, "version": chiapos_version},
                "madmax": {"can_install": True, "display_name": "madMAx Plotter", "installed": False},
            },
        },
    ),
)
@pytest.mark.asyncio
async def test_misc_daemon_ws(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain],
    case: RouteCase,
) -> None:
    ws, _ = daemon_connection_and_temp_keychain

    payload = create_payload(case.route, case.request, "service_name", "daemon")
    await ws.send_str(payload)
    response = await ws.receive()

    assert_response(response, case.response)


@pytest.mark.asyncio
async def test_unexpected_json(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain]
) -> None:
    ws, _ = daemon_connection_and_temp_keychain

    await ws.send_str('{"this": "is valid but not expected"}')  # send some valid but unexpected json
    response = await ws.receive()

    # check for error response
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    assert message["data"]["success"] is False
    assert message["data"]["error"].startswith("'command'")


@pytest.mark.parametrize(
    "command_to_test",
    [("start_service"), ("stop_service"), ("start_plotting"), ("stop_plotting"), ("is_running"), ("register_service")],
)
@pytest.mark.asyncio
async def test_commands_with_no_data(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain], command_to_test: str
) -> None:
    ws, _ = daemon_connection_and_temp_keychain

    payload = create_payload(command_to_test, {}, "service_name", "daemon")

    await ws.send_str(payload)
    response = await ws.receive()

    assert_response(response, {"success": False, "error": f'{command_to_test} requires "data"'})


@datacases(
    RouteCase(
        route="set_keyring_passphrase",
        description="no passphrase",
        request={
            "passphrase_hint": "this is a hint",
            "save_passphrase": False,
        },
        response={"success": False, "error": "missing new_passphrase"},
    ),
    RouteCase(
        route="set_keyring_passphrase",
        description="incorrect type",
        request={
            "passphrase_hint": "this is a hint",
            "save_passphrase": False,
            "new_passphrase": True,
        },
        response={"success": False, "error": "missing new_passphrase"},
    ),
    RouteCase(
        route="set_keyring_passphrase",
        description="correct",
        request={
            "passphrase_hint": "this is a hint",
            "new_passphrase": "this is a passphrase",
        },
        response={"success": True, "error": None},
    ),
)
@pytest.mark.asyncio
async def test_set_keyring_passphrase_ws(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain],
    case: RouteCase,
) -> None:
    ws, _ = daemon_connection_and_temp_keychain

    payload = create_payload(case.route, case.request, "service_name", "daemon")
    await ws.send_str(payload)
    response = await ws.receive()

    assert_response(response, case.response)


@datacases(
    RouteCase(
        route="remove_keyring_passphrase",
        description="wrong current passphrase",
        request={"current_passphrase": "wrong passphrase"},
        response={"success": False, "error": "current passphrase is invalid"},
    ),
    RouteCase(
        route="remove_keyring_passphrase",
        description="incorrect type",
        request={"current_passphrase": True},
        response={"success": False, "error": "missing current_passphrase"},
    ),
    RouteCase(
        route="remove_keyring_passphrase",
        description="missing current passphrase",
        request={},
        response={"success": False, "error": "missing current_passphrase"},
    ),
    RouteCase(
        route="remove_keyring_passphrase",
        description="correct",
        request={"current_passphrase": "this is a passphrase"},
        response={"success": True, "error": None},
    ),
    RouteCase(
        route="unlock_keyring",
        description="wrong current passphrase",
        request={"key": "wrong passphrase"},
        response={"success": False, "error": "bad passphrase"},
    ),
    RouteCase(
        route="unlock_keyring",
        description="incorrect type",
        request={"key": True},
        response={"success": False, "error": "missing key"},
    ),
    RouteCase(
        route="unlock_keyring",
        description="missing data",
        request={},
        response={"success": False, "error": "missing key"},
    ),
    RouteCase(
        route="unlock_keyring",
        description="correct",
        request={"key": "this is a passphrase"},
        response={"success": True, "error": None},
    ),
    RouteCase(
        route="set_keyring_passphrase",
        description="no current passphrase",
        request={
            "save_passphrase": False,
            "new_passphrase": "another new passphrase",
        },
        response={"success": False, "error": "missing current_passphrase"},
    ),
    RouteCase(
        route="set_keyring_passphrase",
        description="incorrect current passphrase",
        request={
            "save_passphrase": False,
            "current_passphrase": "none",
            "new_passphrase": "another new passphrase",
        },
        response={"success": False, "error": "current passphrase is invalid"},
    ),
    RouteCase(
        route="set_keyring_passphrase",
        description="incorrect type",
        request={
            "save_passphrase": False,
            "current_passphrase": False,
            "new_passphrase": "another new passphrase",
        },
        response={"success": False, "error": "missing current_passphrase"},
    ),
    RouteCase(
        route="set_keyring_passphrase",
        description="correct",
        request={
            "save_passphrase": False,
            "current_passphrase": "this is a passphrase",
            "new_passphrase": "another new passphrase",
        },
        response={"success": True, "error": None},
    ),
)
@pytest.mark.asyncio
async def test_passphrase_apis(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain],
    case: RouteCase,
) -> None:
    ws, keychain = daemon_connection_and_temp_keychain

    keychain.set_master_passphrase(
        current_passphrase=DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, new_passphrase="this is a passphrase"
    )

    payload = create_payload(
        case.route,
        case.request,
        "service_name",
        "daemon",
    )
    await ws.send_str(payload)
    response = await ws.receive()

    assert_response(response, case.response)


@datacases(
    RouteCase(
        route="unlock_keyring",
        description="exception",
        request={"key": "this is a passphrase"},
        response={"success": False, "error": "validation exception"},
    ),
    RouteCase(
        route="validate_keyring_passphrase",
        description="exception",
        request={"key": "this is a passphrase"},
        response={"success": False, "error": "validation exception"},
    ),
)
@pytest.mark.asyncio
async def test_keyring_file_deleted(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain],
    case: RouteCase,
) -> None:
    ws, keychain = daemon_connection_and_temp_keychain

    keychain.set_master_passphrase(
        current_passphrase=DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, new_passphrase="this is a passphrase"
    )
    keychain.keyring_wrapper.keyring.keyring_path.unlink()

    payload = create_payload(
        case.route,
        case.request,
        "service_name",
        "daemon",
    )
    await ws.send_str(payload)
    response = await ws.receive()

    assert_response(response, case.response)


@datacases(
    RouteCase(
        route="start_plotting",
        description="chiapos - missing k",
        request={k: v for k, v in plotter_request_ref.items() if k != "k"},
        response={"success": False, "error": "'k'"},
    ),
    RouteCase(
        route="start_plotting",
        description="chiapos - missing d",
        request={k: v for k, v in plotter_request_ref.items() if k != "d"},
        response={"success": False, "error": "'d'"},
    ),
    RouteCase(
        route="start_plotting",
        description="chiapos - missing t",
        request={k: v for k, v in plotter_request_ref.items() if k != "t"},
        response={"success": False, "error": "'t'"},
    ),
    RouteCase(
        route="start_plotting",
        description="chiapos - both c and p",
        request={
            **plotter_request_ref,
            "c": "hello",
            "p": "goodbye",
        },
        response={
            "success": False,
            "service_name": "chia_plotter",
            "error": "Choose one of pool_contract_address and pool_public_key",
        },
    ),
)
@pytest.mark.asyncio
async def test_plotter_errors(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain], case: RouteCase
) -> None:
    ws, keychain = daemon_connection_and_temp_keychain

    payload = create_payload(
        case.route,
        case.request,
        "test_service_name",
        "daemon",
    )
    await ws.send_str(payload)
    response = await ws.receive()

    assert_response(response, case.response)


@datacases(
    RouteCase(
        route="start_plotting",
        description="bladebit - ramplot",
        request={
            **plotter_request_ref,
            "plotter": "bladebit",
            "plot_type": "ramplot",
            "w": True,
            "m": True,
            "no_cpu_affinity": True,
            "e": False,
        },
        response={
            "success": True,
        },
    ),
    RouteCase(
        route="start_plotting",
        description="bladebit - diskplot",
        request={
            **plotter_request_ref,
            "plotter": "bladebit",
            "plot_type": "diskplot",
            "w": True,
            "m": True,
            "no_cpu_affinity": True,
            "e": False,
            "cache": "cache",
            "f1_threads": 5,
            "fp_threads": 6,
            "c_threads": 4,
            "p2_threads": 4,
            "p3_threads": 4,
            "alternate": True,
            "no_t1_direct": True,
            "no_t2_direct": True,
        },
        response={
            "success": True,
        },
    ),
    RouteCase(
        route="start_plotting",
        description="madmax",
        request={
            **plotter_request_ref,
            "plotter": "madmax",
            "w": True,
            "m": True,
            "no_cpu_affinity": True,
            "t2": "testing",
            "v": 128,
        },
        response={
            "success": True,
        },
    ),
)
@pytest.mark.asyncio
async def test_plotter_options(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain],
    get_b_tools: BlockTools,
    case: RouteCase,
) -> None:
    ws, keychain = daemon_connection_and_temp_keychain

    # register for chia_plotter events
    service_name = "chia_plotter"
    data = {"service": service_name}
    payload = create_payload("register_service", data, "chia_plotter", "daemon")
    await ws.send_str(payload)
    response = await ws.receive()
    assert_response_success_only(response)

    case.request["t"] = str(get_b_tools.root_path)
    case.request["d"] = str(get_b_tools.root_path)

    payload_rpc = create_payload_dict(
        case.route,
        case.request,
        "test_service_name",
        "daemon",
    )
    payload = dict_to_json_str(payload_rpc)
    await ws.send_str(payload)
    response = await ws.receive()

    assert_response_success_only(response, payload_rpc["request_id"])


def assert_plot_queue_response(
    response: aiohttp.http_websocket.WSMessage,
    expected_command: str,
    expected_message_state: str,
    expected_plot_id: str,
    expected_plot_state: str,
) -> None:
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    assert message["command"] == expected_command
    assert message["data"]["state"] == expected_message_state
    plot_info = message["data"]["queue"][0]
    assert plot_info["id"] == expected_plot_id
    assert plot_info["state"] == expected_plot_state


def check_plot_queue_log(
    response: aiohttp.http_websocket.WSMessage,
    expected_command: str,
    expected_message_state: str,
    expected_plot_id: str,
    expected_plot_state: str,
    expected_log_entry: str,
) -> bool:
    assert_plot_queue_response(
        response, expected_command, expected_message_state, expected_plot_id, expected_plot_state
    )

    message = json.loads(response.data.strip())
    plot_info = message["data"]["queue"][0]

    return plot_info["log_new"].startswith(expected_log_entry)


@pytest.mark.asyncio
async def test_plotter_roundtrip(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain], get_b_tools: BlockTools
) -> None:
    ws, keychain = daemon_connection_and_temp_keychain

    # register for chia_plotter events
    service_name = "chia_plotter"
    data = {"service": service_name}
    payload = create_payload("register_service", data, "chia_plotter", "daemon")
    await ws.send_str(payload)
    response = await ws.receive()
    assert_response_success_only(response)

    root_path = get_b_tools.root_path

    plotting_request: Dict[str, Any] = {
        **plotter_request_ref,
        "d": str(root_path),
        "t": str(root_path),
        "p": "xxx",
    }
    plotting_request.pop("c", None)

    payload_rpc = create_payload_dict(
        "start_plotting",
        plotting_request,
        "test_service_name",
        "daemon",
    )
    payload = dict_to_json_str(payload_rpc)
    await ws.send_str(payload)

    # should first get response to start_plottin
    response = await ws.receive()
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    assert message["data"]["success"] is True
    assert message["request_id"] == payload_rpc["request_id"]
    plot_id = message["data"]["ids"][0]

    # 1) Submitted
    response = await ws.receive()
    assert_plot_queue_response(response, "state_changed", "state_changed", plot_id, "SUBMITTED")

    # 2) Running
    response = await ws.receive()
    assert_plot_queue_response(response, "state_changed", "state_changed", plot_id, "RUNNING")

    # Write chiapos magic words to the log file to signal finished
    plot_log_path = plotter_log_path(root_path, plot_id)
    with open(plot_log_path, "a") as f:
        f.write("Renamed final file")
        f.flush()

    # 3) log_changed
    final_log_entry = False
    while not final_log_entry:
        response = await ws.receive()
        final_log_entry = check_plot_queue_log(
            response, "state_changed", "log_changed", plot_id, "RUNNING", "Renamed final file"
        )
        if not final_log_entry:
            with open(plot_log_path, "a") as f:
                f.write("Renamed final file")
                f.flush()

    # 4) Finished
    response = await ws.receive()
    assert_plot_queue_response(response, "state_changed", "state_changed", plot_id, "FINISHED")


@pytest.mark.asyncio
async def test_plotter_stop_plotting(
    daemon_connection_and_temp_keychain: Tuple[aiohttp.ClientWebSocketResponse, Keychain], get_b_tools: BlockTools
) -> None:
    ws, keychain = daemon_connection_and_temp_keychain

    # register for chia_plotter events
    service_name = "chia_plotter"
    data = {"service": service_name}
    payload = create_payload("register_service", data, "chia_plotter", "daemon")
    await ws.send_str(payload)
    response = await ws.receive()
    assert_response_success_only(response)

    root_path = get_b_tools.root_path

    plotting_request: Dict[str, Any] = {
        **plotter_request_ref,
        "d": str(root_path),
        "t": str(root_path),
    }

    payload_rpc = create_payload_dict(
        "start_plotting",
        plotting_request,
        "test_service_name",
        "daemon",
    )
    payload = dict_to_json_str(payload_rpc)
    await ws.send_str(payload)

    # should first get response to start_plotting
    response = await ws.receive()
    assert response.type == aiohttp.WSMsgType.TEXT
    message = json.loads(response.data.strip())
    assert message["data"]["success"] is True
    # make sure matches the start_plotting request
    assert message["request_id"] == payload_rpc["request_id"]
    plot_id = message["data"]["ids"][0]

    # 1) Submitted
    response = await ws.receive()
    assert_plot_queue_response(response, "state_changed", "state_changed", plot_id, "SUBMITTED")

    # 2) Running
    response = await ws.receive()
    assert_plot_queue_response(response, "state_changed", "state_changed", plot_id, "RUNNING")

    payload_rpc = create_payload_dict(
        "stop_plotting",
        {"id": plot_id},
        "service_name",
        "daemon",
    )

    stop_plotting_request_id = payload_rpc["request_id"]
    payload = dict_to_json_str(payload_rpc)
    await ws.send_str(payload)

    # 3) removing
    response = await ws.receive()
    assert_plot_queue_response(response, "state_changed", "state_changed", plot_id, "REMOVING")

    # 4) Finished
    response = await ws.receive()
    assert_plot_queue_response(response, "state_changed", "state_changed", plot_id, "FINISHED")

    # 5) Finally, get the "ack" for the stop_plotting payload
    response = await ws.receive()
    assert_response(response, {"success": True}, stop_plotting_request_id)
