from __future__ import annotations

import contextlib
import dataclasses
import logging
import ssl
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

import aiohttp
import pytest
from chia_rs.sized_ints import uint16

from chia.rpc.rpc_server import Endpoint, EndpointResult, RpcServer, RpcServiceProtocol
from chia.ssl.create_ssl import create_all_ssl
from chia.util.config import load_config
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

    async def _state_changed(self, change: str, change_data: Optional[dict[str, Any]] = None) -> list[WsRpcMessage]:
        # just here to satisfy the complete protocol
        return []  # pragma: no cover

    def get_routes(self) -> dict[str, Endpoint]:
        return {
            "/log": self.log,
        }

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

    async def request(self, endpoint: str, json: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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
