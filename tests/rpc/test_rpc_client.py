from __future__ import annotations

import pytest

from chia.rpc.rpc_client import RpcClient
from tests.util.misc import RecordingWebServer


@pytest.mark.anyio
async def test_rpc_client_works_without_ssl(recording_web_server: RecordingWebServer) -> None:
    expected_result = {"success": True, "daddy": "putdown"}

    async with RpcClient.create_as_context(
        self_hostname=recording_web_server.web_server.hostname,
        port=recording_web_server.web_server.listen_port,
    ) as rpc_client:
        result = await rpc_client.fetch(path="", request_json={"response": expected_result})

    assert result == expected_result
