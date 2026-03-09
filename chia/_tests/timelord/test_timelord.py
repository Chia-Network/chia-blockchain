from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chia.timelord.timelord import Timelord
from chia.timelord.timelord_service import TimelordService


@pytest.mark.anyio
async def test_timelord_has_no_server(timelord_service: TimelordService) -> None:
    timelord_server = timelord_service._node.server
    assert timelord_server.webserver is None


def _make_mock_writer(ip: str = "127.0.0.1") -> MagicMock:
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.get_extra_info.return_value = (ip, 12345)
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


def _make_timelord_stub(ip_whitelist: list[str]) -> Timelord:
    with patch.object(Timelord, "__init__", lambda self, *a, **kw: None):
        tl = Timelord.__new__(Timelord)
    tl.free_clients = []
    tl.max_free_clients = 10
    tl.ip_whitelist = ip_whitelist
    tl.lock = asyncio.Lock()
    return tl


class TestHandleClient:
    @pytest.mark.anyio
    async def test_non_whitelisted_ip_is_rejected_and_closed(self) -> None:
        tl = _make_timelord_stub(ip_whitelist=["127.0.0.1"])
        reader = MagicMock(spec=asyncio.StreamReader)
        writer = _make_mock_writer(ip="10.0.0.99")

        await tl._handle_client(reader, writer)

        assert len(tl.free_clients) == 0
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    @pytest.mark.anyio
    async def test_whitelisted_ip_is_accepted(self) -> None:
        tl = _make_timelord_stub(ip_whitelist=["127.0.0.1"])
        reader = MagicMock(spec=asyncio.StreamReader)
        writer = _make_mock_writer(ip="127.0.0.1")

        await tl._handle_client(reader, writer)

        assert len(tl.free_clients) == 1
        assert tl.free_clients[0] == ("127.0.0.1", reader, writer)
        writer.close.assert_not_called()

    @pytest.mark.anyio
    async def test_excess_clients_beyond_cap_are_rejected(self) -> None:
        tl = _make_timelord_stub(ip_whitelist=["127.0.0.1"])
        tl.max_free_clients = 3

        for _ in range(3):
            reader = MagicMock(spec=asyncio.StreamReader)
            writer = _make_mock_writer(ip="127.0.0.1")
            await tl._handle_client(reader, writer)

        assert len(tl.free_clients) == 3

        overflow_reader = MagicMock(spec=asyncio.StreamReader)
        overflow_writer = _make_mock_writer(ip="127.0.0.1")
        await tl._handle_client(overflow_reader, overflow_writer)

        assert len(tl.free_clients) == 3
        overflow_writer.close.assert_called_once()
        overflow_writer.wait_closed.assert_awaited_once()
