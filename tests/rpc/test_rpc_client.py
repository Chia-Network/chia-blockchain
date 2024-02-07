from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from chia.rpc.rpc_client import RpcClient
from chia.util.ints import uint16
from tests.util.misc import Marks, RecordingWebServer, datacases


@dataclass
class InvalidCreateCase:
    id: str
    root_path: Optional[Path] = None
    net_config: Optional[Dict[str, Any]] = None
    marks: Marks = ()


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
