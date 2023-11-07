from __future__ import annotations

import pytest

from chia.server.start_service import Service
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI


@pytest.mark.anyio
async def test_timelord_has_no_server(timelord_service: Service[Timelord, TimelordAPI]) -> None:
    timelord_server = timelord_service._node.server
    assert timelord_server.webserver is None
