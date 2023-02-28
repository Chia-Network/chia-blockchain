from __future__ import annotations

import aiohttp
import pytest

from chia.daemon.server import WebSocketServer
from chia.simulator.block_tools import BlockTools
from chia.util.ws_message import create_payload


@pytest.mark.asyncio
async def test_multiple_register_same(get_daemon: WebSocketServer, bt: BlockTools) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    async with aiohttp.ClientSession() as client:
        ws = await client.ws_connect(
            f"wss://127.0.0.1:{daemon_port}",
            autoclose=True,
            autoping=True,
            ssl_context=bt.get_daemon_ssl_context(),
            max_msg_size=100 * 1024 * 1024,
        )

        service_name = "test_service"
        data = {"service": service_name}
        payload = create_payload("register_service", data, service_name, "daemon")
        for _ in range(4):
            await ws.send_str(payload)
            await ws.receive()

    connections = ws_server.connections.get(service_name, set())
    assert len(connections) == 1


@pytest.mark.asyncio
async def test_multiple_register_different(get_daemon: WebSocketServer, bt: BlockTools) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    async with aiohttp.ClientSession() as client:
        ws = await client.ws_connect(
            f"wss://127.0.0.1:{daemon_port}",
            autoclose=True,
            autoping=True,
            ssl_context=bt.get_daemon_ssl_context(),
            max_msg_size=100 * 1024 * 1024,
        )

        test_service_names = ["service1", "service2", "service3"]

        for service_name in test_service_names:
            data = {"service": service_name}
            payload = create_payload("register_service", data, service_name, "daemon")
            await ws.send_str(payload)
            await ws.receive()

        assert len(ws_server.connections.keys()) == len(test_service_names)

        for service_name in test_service_names:
            connections = ws_server.connections.get(service_name, set())
            assert len(connections) == 1

        await ws.close()

        for service_name in test_service_names:
            connections = ws_server.connections.get(service_name, set())
            assert len(connections) == 0


@pytest.mark.asyncio
async def test_remove_connection(get_daemon: WebSocketServer, bt: BlockTools) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    async with aiohttp.ClientSession() as client:
        ws = await client.ws_connect(
            f"wss://127.0.0.1:{daemon_port}",
            autoclose=True,
            autoping=True,
            ssl_context=bt.get_daemon_ssl_context(),
            max_msg_size=100 * 1024 * 1024,
        )

        test_service_names = ["service1", "service2", "service3", "service4", "service5"]

        for service_name in test_service_names:
            data = {"service": service_name}
            payload = create_payload("register_service", data, service_name, "daemon")
            await ws.send_str(payload)
            await ws.receive()

    assert len(ws_server.connections.keys()) == len(test_service_names)

    connections = ws_server.connections.get(test_service_names[0], set())
    assert len(connections) == 1
    ws_to_remove = next(iter(connections))

    removed_names = ws_server.remove_connection(ws_to_remove)
    assert removed_names == test_service_names

    # remove again, should return empty set and not raise any errors
    removed_names = ws_server.remove_connection(ws_to_remove)
    assert len(removed_names) == 0
