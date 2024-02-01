from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import pytest

from chia.cmds.cmds_util import get_any_service_client
from chia.rpc.rpc_client import ResponseFailureError, RpcClient
from tests.util.misc import RecordingWebServer

# TODO: think about where these tests actually belong

sample_traceback = "this\nthat"
sample_traceback_json = json.dumps(sample_traceback)


@pytest.fixture(name="rpc_client")
async def rpc_client_fixture(recording_web_server: RecordingWebServer) -> AsyncIterator[RpcClient]:
    async with RpcClient.create_as_context(
        self_hostname=recording_web_server.web_server.hostname,
        port=recording_web_server.web_server.listen_port,
    ) as rpc_client:
        yield rpc_client


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


@pytest.mark.anyio
async def test_failure_output_no_traceback(
    root_path_populated_with_config: Path,
    recording_web_server: RecordingWebServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_response = {"success": False, "magic": "statue"}

    async with get_any_service_client(
        client_type=RpcClient,
        rpc_port=recording_web_server.web_server.listen_port,
        root_path=root_path_populated_with_config,
        use_ssl=False,
    ) as (client, _):
        await client.fetch(path="/table", request_json={"response": expected_response})

    out, err = capsys.readouterr()

    assert "ResponseFailureError" not in out
    assert "Traceback:" not in out
    assert json.dumps(expected_response) in out


@pytest.mark.anyio
async def test_failure_output_with_traceback(
    root_path_populated_with_config: Path,
    recording_web_server: RecordingWebServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_response = {"success": False, "traceback": sample_traceback}

    async with get_any_service_client(
        client_type=RpcClient,
        rpc_port=recording_web_server.web_server.listen_port,
        root_path=root_path_populated_with_config,
        use_ssl=False,
    ) as (client, _):
        await client.fetch(path="/table", request_json={"response": expected_response})

    out, err = capsys.readouterr()
    assert sample_traceback_json not in out
    assert sample_traceback in out
