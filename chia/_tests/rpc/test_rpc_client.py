from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import pytest
from chia_rs.sized_ints import uint16

from chia._tests.util.misc import Marks, RecordingWebServer, datacases
from chia.protocols.outbound_message import NodeType
from chia.rpc.rpc_client import ResponseFailureError, RpcClient
from chia.rpc.rpc_server import RpcServer

non_fetch_client_methods = {
    RpcClient.create,
    RpcClient.create_as_context,
    RpcClient.fetch,
    RpcClient.close,
    RpcClient.await_closed,
}

client_fetch_methods = [
    attribute
    for name, attribute in vars(RpcClient).items()
    if callable(attribute) and attribute not in non_fetch_client_methods and not name.startswith("__")
]


@dataclass
class InvalidCreateCase:
    id: str
    root_path: Optional[Path] = None
    net_config: Optional[dict[str, Any]] = None
    marks: Marks = ()


@pytest.fixture(name="rpc_client")
async def rpc_client_fixture(recording_web_server: RecordingWebServer) -> AsyncIterator[RpcClient]:
    async with RpcClient.create_as_context(
        self_hostname=recording_web_server.web_server.hostname,
        port=recording_web_server.web_server.listen_port,
    ) as rpc_client:
        yield rpc_client


@datacases(
    InvalidCreateCase(id="just root path", root_path=Path("/root/path")),
    InvalidCreateCase(id="just net config", net_config={}),
)
@pytest.mark.anyio
async def test_rpc_client_create_raises_for_invalid_root_path_net_config_combinations(
    case: InvalidCreateCase,
) -> None:
    with pytest.raises(ValueError, match="Either both or neither of"):
        await RpcClient.create(
            self_hostname="",
            port=uint16(0),
            root_path=case.root_path,
            net_config=case.net_config,
        )


@pytest.mark.anyio
async def test_rpc_client_works_without_ssl(recording_web_server: RecordingWebServer) -> None:
    expected_result = {"success": True, "daddy": "putdown"}

    async with RpcClient.create_as_context(
        self_hostname=recording_web_server.web_server.hostname,
        port=recording_web_server.web_server.listen_port,
    ) as rpc_client:
        result = await rpc_client.fetch(path="", request_json={"response": expected_result})

    assert result == expected_result


@pytest.mark.anyio
async def test_rpc_client_send_request(
    rpc_client: RpcClient,
) -> None:
    expected_response = {"success": True, "magic": "asparagus"}

    response = await rpc_client.fetch(path="/table", request_json={"response": expected_response})

    assert response == expected_response


@pytest.mark.anyio
async def test_failure_exception(
    rpc_client: RpcClient,
) -> None:
    expected_response = {"success": False, "magic": "xylophone"}

    with pytest.raises(ResponseFailureError) as exception_info:
        await rpc_client.fetch(path="/table", request_json={"response": expected_response})

    assert exception_info.value.response == expected_response


def test_client_standard_endpoints_match_server() -> None:
    # NOTE: this test assumes that the client method names should match the server
    #       route names
    client_method_names = {method.__name__ for method in client_fetch_methods}
    server_route_names = {method.lstrip("/") for method in RpcServer._routes.keys()}
    assert client_method_names == server_route_names


@pytest.mark.anyio
@pytest.mark.parametrize("client_method", client_fetch_methods)
async def test_client_fetch_methods(
    client_method: Callable[..., Awaitable[object]],
    rpc_client: RpcClient,
    recording_web_server: RecordingWebServer,
) -> None:
    # NOTE: this test assumes that the client method names should match the server
    #       route names

    parameters: dict[Callable[..., Awaitable[object]], dict[str, object]] = {
        RpcClient.open_connection: {"host": "", "port": 0},
        RpcClient.close_connection: {"node_id": b""},
        RpcClient.get_connections: {"node_type": NodeType.FULL_NODE},
        RpcClient.set_log_level: {"level": "DEBUG"},
    }

    try:
        await client_method(rpc_client, **parameters.get(client_method, {}))
    except Exception as exception:
        if client_method is RpcClient.get_connections and isinstance(exception, KeyError):
            pass
        else:  # pragma: no cover
            # this case will fail the test so not normally executed
            raise

    [request] = recording_web_server.requests
    assert request.content_type == "application/json"
    assert request.method == "POST"
    assert request.path == f"/{client_method.__name__}"
