from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from chia.util.ws_message import create_payload


@pytest.mark.asyncio
async def test_multiple_register_same(get_daemon: Any, bt: Any) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    client = aiohttp.ClientSession()
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
    await ws.send_str(payload)
    await ws.receive()
    payload = create_payload("register_service", data, service_name, "daemon")
    await ws.send_str(payload)
    await ws.receive()
    payload = create_payload("register_service", data, service_name, "daemon")
    await ws.send_str(payload)
    await ws.receive()
    payload = create_payload("register_service", data, service_name, "daemon")
    await ws.send_str(payload)
    await ws.receive()

    connections = ws_server.connections.get(service_name, {})
    assert len(connections) == 1

    await client.close()
    await ws_server.stop()


@pytest.mark.asyncio
async def test_multiple_register_different(get_daemon: Any, bt: Any) -> None:
    ws_server = get_daemon
    config = bt.config

    daemon_port = config["daemon_port"]

    # setup receive service to connect to the daemon
    client = aiohttp.ClientSession()
    ws = await client.ws_connect(
        f"wss://127.0.0.1:{daemon_port}",
        autoclose=True,
        autoping=True,
        ssl_context=bt.get_daemon_ssl_context(),
        max_msg_size=100 * 1024 * 1024,
    )

    # register service 1
    service1 = "test_service"
    data = {"service": service1}
    payload = create_payload("register_service", data, service1, "daemon")
    await ws.send_str(payload)
    await ws.receive()

    # using same ws, register service 2
    service2 = "other_service"
    data = {"service": service2}
    payload = create_payload("register_service", data, service2, "daemon")
    await ws.send_str(payload)
    await ws.receive()

    connections = ws_server.connections.get(service1, {})
    assert len(connections) == 1

    connections = ws_server.connections.get(service2, {})
    assert len(connections) == 1

    await ws.close()

    connections = ws_server.connections.get(service1, {})
    assert len(connections) == 0

    connections = ws_server.connections.get(service2, {})
    assert len(connections) == 0

    await client.close()
    await ws_server.stop()
