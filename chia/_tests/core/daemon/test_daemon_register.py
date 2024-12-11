from __future__ import annotations

import contextlib
from collections import defaultdict

import aiohttp
import pytest

from chia.daemon.server import WebSocketServer
from chia.simulator.block_tools import BlockTools
from chia.util.ws_message import create_payload

pytestmark = [
    pytest.mark.limit_consensus_modes(reason="irrelevant"),
]


@pytest.mark.anyio
async def test_multiple_register_same(get_daemon: WebSocketServer, bt: BlockTools) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(
            f"wss://127.0.0.1:{daemon_port}",
            autoclose=True,
            autoping=True,
            ssl=bt.get_daemon_ssl_context(),
            max_msg_size=100 * 1024 * 1024,
        ) as ws:
            service_name = "test_service"
            data = {"service": service_name}
            payload = create_payload("register_service", data, service_name, "daemon")
            for _ in range(4):
                await ws.send_str(payload)
                await ws.receive()

            connections = ws_server.connections.get(service_name, set())
            assert len(connections) == 1


@pytest.mark.anyio
async def test_multiple_register_different(get_daemon: WebSocketServer, bt: BlockTools) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(
            f"wss://127.0.0.1:{daemon_port}",
            autoclose=True,
            autoping=True,
            ssl=bt.get_daemon_ssl_context(),
            max_msg_size=100 * 1024 * 1024,
        ) as ws:
            test_service_names = ["service1", "service2", "service3"]

            for service_name in test_service_names:
                data = {"service": service_name}
                payload = create_payload("register_service", data, service_name, "daemon")
                await ws.send_str(payload)
                await ws.receive()

            assert sorted(ws_server.connections.keys()) == test_service_names

            for service_name in test_service_names:
                connections = ws_server.connections.get(service_name, set())
                assert len(connections) == 1

        # Check after closing the connection
        for service_name in test_service_names:
            connections = ws_server.connections.get(service_name, set())
            assert connections == set()


@pytest.mark.anyio
async def test_remove_connection(get_daemon: WebSocketServer, bt: BlockTools) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(
            f"wss://127.0.0.1:{daemon_port}",
            autoclose=True,
            autoping=True,
            ssl=bt.get_daemon_ssl_context(),
            max_msg_size=100 * 1024 * 1024,
        ) as ws:
            test_service_names = ["service1", "service2", "service3", "service4", "service5"]

            for service_name in test_service_names:
                data = {"service": service_name}
                payload = create_payload("register_service", data, service_name, "daemon")
                await ws.send_str(payload)
                await ws.receive()

            assert sorted(ws_server.connections.keys()) == test_service_names

            connections = ws_server.connections.get(test_service_names[0], set())
            assert len(connections) == 1
            ws_to_remove = next(iter(connections))

            removed_names = ws_server.remove_connection(ws_to_remove)
            assert removed_names == test_service_names

            # remove again, should return empty list and not raise any errors
            removed_names = ws_server.remove_connection(ws_to_remove)
            assert removed_names == list()


@pytest.mark.anyio
async def test_multiple_register_same_or_something_huh(get_daemon: WebSocketServer, bt: BlockTools) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    async with contextlib.AsyncExitStack() as exit_stack:
        client = await exit_stack.enter_async_context(aiohttp.ClientSession())
        total_connection_count = 5
        websockets = [
            await exit_stack.enter_async_context(
                client.ws_connect(
                    f"wss://127.0.0.1:{daemon_port}",
                    autoclose=True,
                    autoping=True,
                    ssl=bt.get_daemon_ssl_context(),
                    max_msg_size=100 * 1024 * 1024,
                )
            )
            for _ in range(total_connection_count)
        ]

        service_name = "test_service"
        data = {"service": service_name}
        payload = create_payload("register_service", data, service_name, "daemon")
        for websocket in websockets:
            for _ in range(5):
                await websocket.send_str(payload)
                await websocket.receive()

        connections = ws_server.connections[service_name]
        assert len(connections) == total_connection_count

        ws_server.state_changed(service=service_name, message={"grannies": "can"})

        results = defaultdict(list)
        for websocket in websockets:
            while True:
                try:
                    results[websocket].append(await websocket.receive(timeout=1))
                except TimeoutError:
                    break

        assert all(len(result_list) == 1 for result_list in results.values())
