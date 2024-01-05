from __future__ import annotations

import pytest

from chia.types.aliases import TimelordService


@pytest.mark.anyio
async def test_timelord_has_no_server(timelord_service: TimelordService) -> None:
    timelord_server = timelord_service._node.server
    assert timelord_server.webserver is None
