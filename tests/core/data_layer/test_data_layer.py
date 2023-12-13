from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, cast, final

import aiohttp
import pytest
from aiohttp import web

from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_util import PluginRemote
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16
from chia.util.network import WebServer


async def create_sufficient_wallet_rpc_client() -> WalletRpcClient:
    return cast(WalletRpcClient, SufficientWalletRpcClient())


class SufficientWalletRpcClient:
    def close(self) -> None:
        return

    async def await_closed(self) -> None:
        return


@pytest.mark.parametrize(argnames="enable", argvalues=[True, False], ids=["log", "do not log"])
@pytest.mark.anyio
async def test_sql_logs(enable: bool, config: Dict[str, Any], tmp_chia_root: Path) -> None:
    config["data_layer"]["log_sqlite_cmds"] = enable

    log_path = tmp_chia_root.joinpath("log", "data_sql.log")

    data_layer = DataLayer.create(
        config=config["data_layer"],
        root_path=tmp_chia_root,
        wallet_rpc_init=create_sufficient_wallet_rpc_client(),
        downloaders=[],
        uploaders=[],
    )
    assert not log_path.exists()
    async with data_layer.manage():
        pass

    if enable:
        assert log_path.is_file()
    else:
        assert not log_path.exists()


@final
@dataclass
class RecordingWebServer:
    web_server: WebServer
    requests: List[web.Request] = field(default_factory=list)

    @classmethod
    async def create(
        cls,
        hostname: str,
        port: uint16,
        max_request_body_size: int = 1024**2,  # Default `client_max_size` from web.Application
        ssl_context: Optional[ssl.SSLContext] = None,
        prefer_ipv6: bool = False,
    ) -> RecordingWebServer:
        web_server = await WebServer.create(
            hostname=hostname,
            port=port,
            max_request_body_size=max_request_body_size,
            ssl_context=ssl_context,
            prefer_ipv6=prefer_ipv6,
            start=False,
        )

        self = cls(web_server=web_server)
        routes = [web.route(method="*", path=route, handler=func) for (route, func) in self.get_routes().items()]
        web_server.add_routes(routes=routes)
        await web_server.start()
        return self

    def get_routes(self) -> Dict[str, Callable[[web.Request], Awaitable[web.Response]]]:
        return {"/{path:.*}": self.handler}

    async def handler(self, request: web.Request) -> web.Response:
        self.requests.append(request)
        return aiohttp.web.json_response(data={"success": True})

    async def await_closed(self) -> None:
        self.web_server.close()
        await self.web_server.await_closed()


@pytest.fixture(name="recording_web_server")
async def recording_web_server_fixture(self_hostname: str) -> AsyncIterator[RecordingWebServer]:
    server = await RecordingWebServer.create(
        hostname=self_hostname,
        port=uint16(0),
    )
    try:
        yield server
    finally:
        await server.await_closed()


@pytest.mark.anyio
async def test_plugin_requests_use_custom_headers(
    recording_web_server: RecordingWebServer,
    config: Dict[str, Any],
    tmp_chia_root: Path,
) -> None:
    header_key = "vbiuoqemnrlah"
    header_value = "98754718932345"

    plugin_remote = PluginRemote(
        url=recording_web_server.web_server.url(),
        headers={header_key: header_value},
    )

    async def wallet_rpc_init() -> WalletRpcClient:
        # this return is not presently used for this test
        return None  # type: ignore[return-value]

    data_layer = DataLayer.create(
        config=config["data_layer"],
        root_path=tmp_chia_root,
        wallet_rpc_init=wallet_rpc_init(),
        downloaders=[plugin_remote],
        uploaders=[plugin_remote],
    )

    async with data_layer.manage():
        await data_layer.get_downloader(tree_id=bytes32([0] * 32), url="")
        await data_layer.get_uploaders(tree_id=bytes32([0] * 32))
        await data_layer.check_plugins()

    header_values = {request.headers.get(header_key) for request in recording_web_server.requests}
    assert header_values == {header_value}
