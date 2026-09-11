from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import ssl
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import WSMessage, WSMsgType
from chia_rs.sized_ints import uint16

from chia.rpc.rpc_errors import RpcError, RpcErrorCodes
from chia.rpc.rpc_server import Endpoint, EndpointResult, RpcServer, RpcServiceProtocol
from chia.ssl.create_ssl import create_all_ssl
from chia.util.config import load_config
from chia.util.task_referencer import create_referenced_task
from chia.util.ws_message import WsRpcMessage

root_logger = logging.getLogger()

if sys.version_info >= (3, 11):  # pragma: no cover
    name_to_number_level_map = logging.getLevelNamesMapping()
else:
    name_to_number_level_map = logging._nameToLevel

number_to_name_level_map = {number: name for name, number in name_to_number_level_map.items()}

# just picking one for which a config is present
service_name = "full_node"


@dataclasses.dataclass
class TestRpcApi:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcApiProtocol

        _protocol_check: ClassVar[RpcApiProtocol] = cast("TestRpcApi", None)

    # unused as of the initial writing of these tests
    service: RpcServiceProtocol
    service_name: str = service_name
    # released by tests that want the wait_for_gate endpoint to return
    gate: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def _state_changed(self, change: str, change_data: dict[str, Any] | None = None) -> list[WsRpcMessage]:
        # just here to satisfy the complete protocol
        return []  # pragma: no cover

    def get_routes(self) -> dict[str, Endpoint]:
        return {
            "/log": self.log,
            "/raise_rpc_error": self.raise_rpc_error,
            "/raise_generic_error": self.raise_generic_error,
            "/wait_for_gate": self.wait_for_gate,
        }

    async def raise_rpc_error(self, request: dict[str, Any]) -> EndpointResult:
        raise RpcError(
            RpcErrorCodes.UNKNOWN,
            "Test message for backwards compatibility, foo is bar",
            data={"foo": "bar"},
            structured_message="Test message for backwards compatibility",
        )

    async def raise_generic_error(self, request: dict[str, Any]) -> EndpointResult:
        raise ValueError("a non-RPC generic error")

    async def wait_for_gate(self, request: dict[str, Any]) -> EndpointResult:
        await self.gate.wait()
        return {"waited": True}

    async def log(self, request: dict[str, Any]) -> EndpointResult:
        message = request["message"]

        level = name_to_number_level_map[request["level"]]

        root_logger.log(level=level, msg=message)

        return {}


@dataclasses.dataclass
class Client:
    session: aiohttp.ClientSession
    ssl_context: ssl.SSLContext
    url: str

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(cls, ssl_context: ssl.SSLContext, url: str) -> AsyncIterator[Client]:
        async with aiohttp.ClientSession() as session:
            yield cls(session=session, ssl_context=ssl_context, url=url)

    async def request(self, endpoint: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        if json is None:
            json = {}

        async with self.session.post(
            self.url.rstrip("/") + "/" + endpoint.lstrip("/"),
            json=json,
            ssl=self.ssl_context,
        ) as response:
            response.raise_for_status()
            json = await response.json()

        assert json is not None
        assert json["success"], json

        return json

    async def request_allow_failure(self, endpoint: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        if json is None:
            json = {}

        async with self.session.post(
            self.url.rstrip("/") + "/" + endpoint.lstrip("/"),
            json=json,
            ssl=self.ssl_context,
        ) as response:
            response.raise_for_status()
            body: dict[str, Any] = await response.json()
        assert body is not None
        return body

    async def log(self, level: str, message: str) -> None:
        await self.request("log", json={"message": message, "level": level})


@pytest.fixture(name="server")
async def server_fixture(
    root_path_populated_with_config: Path,
    self_hostname: str,
) -> AsyncIterator[RpcServer[TestRpcApi]]:
    config = load_config(root_path=root_path_populated_with_config, filename="config.yaml")
    service_config = config[service_name]

    create_all_ssl(root_path=root_path_populated_with_config)
    rpc_server = RpcServer.create(
        # the test rpc api doesn't presently need a real service for these tests
        rpc_api=TestRpcApi(service=None),  # type: ignore[arg-type]
        service_name="test_rpc_server",
        stop_cb=lambda: None,
        root_path=root_path_populated_with_config,
        net_config=config,
        service_config=service_config,
        prefer_ipv6=False,
    )

    try:
        await rpc_server.start(
            self_hostname=self_hostname,
            rpc_port=uint16(0),
            max_request_body_size=2**16,
        )

        yield rpc_server
    finally:
        rpc_server.close()
        await rpc_server.await_closed()


@pytest.fixture(name="client")
async def client_fixture(
    server: RpcServer[TestRpcApi],
) -> AsyncIterator[Client]:
    assert server.webserver is not None
    async with Client.managed(ssl_context=server.ssl_client_context, url=server.webserver.url()) as client:
        yield client


@pytest.mark.anyio
async def test_get_log_level(
    client: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    level = "WARNING"
    root_logger.setLevel(level)
    result = await client.request("get_log_level")
    assert result["level"] == number_to_name_level_map[root_logger.level]


@pytest.mark.anyio
async def test_set_log_level(
    client: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    message = "just a maybe unique probably message"

    level = "WARNING"
    await client.request("set_log_level", json={"level": level})
    assert number_to_name_level_map[root_logger.level] == level

    caplog.clear()
    await client.log(message=message, level="WARNING")
    assert caplog.messages == [message]

    caplog.clear()
    await client.log(message=message, level="INFO")
    assert caplog.messages == []


@pytest.mark.anyio
async def test_reset_log_level(
    client: Client,
    server: RpcServer[TestRpcApi],
) -> None:
    configured_level = server.service_config["logging"]["log_level"]
    temporary_level = "INFO"
    assert configured_level != temporary_level

    root_logger.setLevel(temporary_level)
    assert number_to_name_level_map[root_logger.level] == temporary_level

    await client.request("reset_log_level")
    assert number_to_name_level_map[root_logger.level] == configured_level


@pytest.mark.anyio
async def test_structured_error_response_shape(client: Client) -> None:
    """RPC error response includes legacy 'error' and 'structuredError' with expected shape."""
    body = await client.request_allow_failure("raise_rpc_error")
    assert body["success"] is False
    assert body["error"] == "Test message for backwards compatibility, foo is bar"
    assert "structuredError" in body
    structured = body["structuredError"]
    assert structured["code"] == "UNKNOWN"
    assert structured["message"] == "Test message for backwards compatibility"
    assert structured["data"] == {"foo": "bar"}


@pytest.mark.anyio
async def test_websocket_structured_error_response(server: RpcServer[TestRpcApi]) -> None:
    """WebSocket error handling includes structuredError in response."""
    # Create a mock WebSocket that captures sent messages
    sent_messages: list[str] = []

    class MockWebSocket:
        async def send_str(self, data: str) -> None:
            sent_messages.append(data)

    mock_ws = MockWebSocket()

    # Send a payload that will trigger the raise_rpc_error endpoint
    payload = json.dumps(
        {
            "command": "raise_rpc_error",
            "data": {},
            "ack": False,
            "request_id": "test-ws-123",
            "destination": "test",
            "origin": "test",
        }
    )

    await server.safe_handle(mock_ws, payload)  # type: ignore[arg-type]

    assert len(sent_messages) == 1
    response = json.loads(sent_messages[0])
    assert response["data"]["success"] is False
    assert response["data"]["error"] == "Test message for backwards compatibility, foo is bar"
    assert "structuredError" in response["data"]
    structured = response["data"]["structuredError"]
    assert structured["code"] == "UNKNOWN"
    assert structured["message"] == "Test message for backwards compatibility"
    assert structured["data"] == {"foo": "bar"}


@pytest.mark.anyio
async def test_websocket_non_rpc_error(server: RpcServer[TestRpcApi]) -> None:
    """Non-RpcError exception through WebSocket produces UNKNOWN code in structuredError."""
    sent_messages: list[str] = []

    class MockWebSocket:
        async def send_str(self, data: str) -> None:
            sent_messages.append(data)

    mock_ws = MockWebSocket()
    payload = json.dumps(
        {
            "command": "raise_generic_error",
            "data": {},
            "ack": False,
            "request_id": "test-generic-err",
            "destination": "test",
            "origin": "test",
        }
    )

    await server.safe_handle(mock_ws, payload)  # type: ignore[arg-type]

    assert len(sent_messages) == 1
    response = json.loads(sent_messages[0])
    assert response["data"]["success"] is False
    assert response["data"]["error"] == "a non-RPC generic error"
    structured = response["data"]["structuredError"]
    assert structured["code"] == "UNKNOWN"
    assert structured["message"] == "a non-RPC generic error"
    assert structured["data"] == {}
    # WebSocket error responses should NOT include traceback
    assert "traceback" not in response["data"]


@pytest.mark.anyio
async def test_safe_handle_invalid_json(server: RpcServer[TestRpcApi]) -> None:
    """safe_handle with unparseable JSON does not crash and sends no response."""
    mock_ws = MagicMock()
    mock_ws.send_str = AsyncMock()
    await server.safe_handle(mock_ws, "not valid json{{{")

    # When message is None (JSON parse failed), no response is sent
    mock_ws.send_str.assert_not_called()


@pytest.mark.anyio
async def test_get_connections_server_none_raises(server: RpcServer[TestRpcApi]) -> None:
    """get_connections raises ValueError when service.server is None."""
    import types

    server.rpc_api.service = types.SimpleNamespace(server=None)

    with pytest.raises(ValueError, match="Global connections is not set"):
        await server.get_connections({})


def daemon_payload(command: str, request_id: str) -> str:
    return json.dumps(
        {
            "command": command,
            "data": {},
            "ack": False,
            "request_id": request_id,
            "destination": "test",
            "origin": "test",
        }
    )


@dataclasses.dataclass
class FakeDaemonWebSocket:
    """Stands in for the service's client websocket to the daemon."""

    incoming: asyncio.Queue[WSMessage] = dataclasses.field(default_factory=asyncio.Queue)
    sent: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    sent_changed: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    closed: bool = False

    def receive_text(self, payload: str) -> None:
        self.incoming.put_nowait(WSMessage(WSMsgType.TEXT, payload, None))

    def close_from_daemon(self) -> None:
        self.closed = True
        self.incoming.put_nowait(WSMessage(WSMsgType.CLOSED, None, None))

    async def receive(self) -> WSMessage:
        return await self.incoming.get()

    async def send_str(self, data: str) -> None:
        if self.closed:
            raise aiohttp.ClientConnectionResetError("Cannot write to closing transport")
        self.sent.append(json.loads(data))
        self.sent_changed.set()

    async def wait_for_sent(self, count: int) -> None:
        async def wait() -> None:
            while len(self.sent) < count:
                self.sent_changed.clear()
                await self.sent_changed.wait()

        await asyncio.wait_for(wait(), timeout=10)


def pending_handler_tasks(server: RpcServer[TestRpcApi]) -> list[asyncio.Task[None]]:
    # finished tasks leave the set from a done callback, which runs a loop iteration after the task ends
    return [task for task in server.daemon_handler_tasks if not task.done()]


@pytest.mark.anyio
async def test_daemon_messages_are_handled_concurrently(server: RpcServer[TestRpcApi]) -> None:
    """A slow handler must not hold back later messages received over the daemon websocket."""
    ws = FakeDaemonWebSocket()
    ws.receive_text(daemon_payload("wait_for_gate", "slow"))
    ws.receive_text(daemon_payload("healthz", "fast"))

    connection_task = create_referenced_task(server.connection(ws))  # type: ignore[arg-type]
    try:
        # the registration and the fast response arrive while the slow handler is still waiting
        await ws.wait_for_sent(2)
        assert ws.sent[0]["command"] == "register_service"
        assert ws.sent[1]["request_id"] == "fast"
        assert ws.sent[1]["data"]["success"] is True
        assert not connection_task.done()
        assert len(pending_handler_tasks(server)) == 1

        server.rpc_api.gate.set()
        await ws.wait_for_sent(3)
        assert ws.sent[2]["request_id"] == "slow"
        assert ws.sent[2]["data"] == {"waited": True, "success": True}

        ws.close_from_daemon()
        await asyncio.wait_for(connection_task, timeout=10)
        assert len(pending_handler_tasks(server)) == 0
    finally:
        server.rpc_api.gate.set()
        connection_task.cancel()


@pytest.mark.anyio
async def test_daemon_connection_loop_ends_while_a_handler_is_in_flight(
    server: RpcServer[TestRpcApi], caplog: pytest.LogCaptureFixture
) -> None:
    """When the daemon closes the connection the loop returns without waiting for in-flight handlers,
    and the reply a handler can no longer deliver is logged rather than raised."""
    ws = FakeDaemonWebSocket()
    ws.receive_text(daemon_payload("wait_for_gate", "slow"))
    ws.receive_text(daemon_payload("healthz", "fast"))

    connection_task = create_referenced_task(server.connection(ws))  # type: ignore[arg-type]
    try:
        # once the fast reply is out, the slow handler is known to be in flight
        await ws.wait_for_sent(2)
        assert ws.sent[0]["command"] == "register_service"
        assert ws.sent[1]["request_id"] == "fast"
        [handler_task] = pending_handler_tasks(server)

        ws.close_from_daemon()
        await asyncio.wait_for(connection_task, timeout=10)
        assert not handler_task.done()

        with caplog.at_level(logging.WARNING, logger="chia.rpc.rpc_server"):
            server.rpc_api.gate.set()
            await asyncio.wait_for(handler_task, timeout=10)

        assert handler_task.exception() is None
        assert "Unable to send the response to 'wait_for_gate'" in caplog.text
        assert len(ws.sent) == 2
        assert len(pending_handler_tasks(server)) == 0
    finally:
        server.rpc_api.gate.set()
        connection_task.cancel()


@pytest.mark.anyio
async def test_await_closed_cancels_in_flight_daemon_handlers(server: RpcServer[TestRpcApi]) -> None:
    ws = FakeDaemonWebSocket()
    ws.receive_text(daemon_payload("wait_for_gate", "slow"))
    ws.receive_text(daemon_payload("healthz", "fast"))

    connection_task = create_referenced_task(server.connection(ws))  # type: ignore[arg-type]
    try:
        await ws.wait_for_sent(2)
        [handler_task] = pending_handler_tasks(server)
        ws.close_from_daemon()
        await asyncio.wait_for(connection_task, timeout=10)

        server.close()
        await asyncio.wait_for(server.await_closed(), timeout=10)

        assert handler_task.cancelled()
        assert len(server.daemon_handler_tasks) == 0
    finally:
        server.rpc_api.gate.set()
        connection_task.cancel()
