from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.timelord import timelord as timelord_module
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_service import TimelordService
from chia.timelord.types import Chain
from chia.types.blockchain_format.classgroup import ClassgroupElement


@pytest.mark.anyio
async def test_timelord_has_no_server(timelord_service: TimelordService) -> None:
    timelord_server = timelord_service._node.server
    assert timelord_server.webserver is None


class _NullTransport(asyncio.Transport):
    def write(self, data: bytes) -> None:
        pass

    def is_closing(self) -> bool:
        return False


def _make_null_writer() -> asyncio.StreamWriter:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    return asyncio.StreamWriter(_NullTransport(), protocol, reader, loop)


@pytest.mark.anyio
async def test_invalid_vdf_proof_is_ignored_in_process_communication(
    timelord_service: TimelordService, monkeypatch: pytest.MonkeyPatch
) -> None:
    timelord = timelord_service._node
    chain = Chain.CHALLENGE_CHAIN
    challenge = bytes32.zeros
    initial_form = ClassgroupElement.get_default_element()
    timelord.chain_start_time[chain] = time.time()

    state_changed_calls: list[object] = []
    monkeypatch.setattr(timelord_module, "validate_vdf", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timelord, "state_changed", lambda *args, **kwargs: state_changed_calls.append((args, kwargs)))

    iterations_needed = uint64(10)
    y_bytes = initial_form.data
    witness_type = 0
    proof_bytes = b"\x01\x02"
    proof_payload = (
        int(iterations_needed).to_bytes(8, "big", signed=True)
        + len(y_bytes).to_bytes(8, "big", signed=True)
        + y_bytes
        + bytes([witness_type])
        + proof_bytes
    )
    encoded_payload = proof_payload.hex().encode()

    reader = asyncio.StreamReader()
    reader.feed_data(b"OK")
    reader.feed_data(len(encoded_payload).to_bytes(4, "big"))
    reader.feed_data(encoded_payload)
    reader.feed_data(b"STOP")
    reader.feed_eof()

    writer = _make_null_writer()
    await timelord._do_process_communication(chain, challenge, initial_form, "127.0.0.1", reader, writer, proof_label=1)

    assert timelord.proofs_finished == []
    assert state_changed_calls == []


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
