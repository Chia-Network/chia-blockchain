from __future__ import annotations

import json
from pathlib import Path

import pytest

from chia._tests.util.misc import RecordingWebServer
from chia.cmds.cmds_util import get_any_service_client
from chia.rpc.rpc_client import ResponseFailureError, RpcClient


@pytest.mark.anyio
async def test_get_any_service_client_works_without_ssl(
    root_path_populated_with_config: Path,
    recording_web_server: RecordingWebServer,
) -> None:
    expected_result = {"success": True, "keepy": "uppy"}

    async with get_any_service_client(
        client_type=RpcClient,
        rpc_port=recording_web_server.web_server.listen_port,
        root_path=root_path_populated_with_config,
        use_ssl=False,
    ) as [rpc_client, _]:
        result = await rpc_client.fetch(path="", request_json={"response": expected_result})

    assert result == expected_result


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
    sample_traceback = "this\nthat"
    sample_traceback_json = json.dumps(sample_traceback)
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


@pytest.mark.anyio
async def test_failure_output_no_consumption(
    root_path_populated_with_config: Path,
    recording_web_server: RecordingWebServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_response = {"success": False, "magic": "xylophone"}

    with pytest.raises(ResponseFailureError) as exception_info:
        async with get_any_service_client(
            client_type=RpcClient,
            rpc_port=recording_web_server.web_server.listen_port,
            root_path=root_path_populated_with_config,
            use_ssl=False,
            consume_errors=False,
        ) as (client, _):
            await client.fetch(path="/table", request_json={"response": expected_response})

    assert exception_info.value.response == expected_response

    assert capsys.readouterr() == ("", "")
